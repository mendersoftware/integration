#!/usr/bin/python3

import argparse
import copy
import json
import operator
import os
import re
import subprocess
import sys
import traceback

try:
    import yaml
except ImportError:
    print("PyYAML missing, try running 'sudo pip3 install pyyaml'.")
    sys.exit(2)

# Disable pager during menu navigation.
os.environ['GIT_PAGER'] = "cat"

# This is basically a YAML file which contains the state of the release process.
# The easiest way to understand its format is by just looking at it after the
# key fields have been filled in. This is updated continuously while the script
# is operating.
# The repositories are indexed by their Git repository names.
RELEASE_STATE = "release-state.yml"

#JENKINS_SERVER = "http://localhost:8080"
JENKINS_SERVER = "https://ci.cfengine.com"
JENKINS_JOB = "job/yoctobuild-kristian"
JENKINS_CRUMB_ISSUER = 'crumbIssuer/api/xml?xpath=concat(//crumbRequestField,":",//crumb)'

VERSION_BUMP_STRING = "Bump versions for Mender"

# Whether or not pushes should really happen.
PUSH = True
# Whether this is a dry-run.
DRY_RUN = False

class RepoName:
    """An object that contains a pair of links for the docker and git names of a
    repository."""

    # Name of container is docker-compose file.
    container = None
    # Name of image in docker hub
    docker = None
    # Name of repository in Git. (what we index by)
    git = None

    def __init__(self, container, docker, git):
        self.container = container
        self.docker = docker
        self.git = git

# All our repos, and also a map from docker-compose container name to all
# names. Everywhere we index using the Git name, unless specified otherwise.
REPOS = {
    "mender-api-gateway": RepoName("mender-api-gateway", "api-gateway", "mender-api-gateway-docker"),
    "mender-client": RepoName("mender-client", "mender-client-qemu", "mender"),
    "mender-deployments": RepoName("mender-deployments", "deployments", "deployments"),
    "mender-device-adm": RepoName("mender-device-adm", "deviceadm", "deviceadm"),
    "mender-device-auth": RepoName("mender-device-auth", "deviceauth", "deviceauth"),
    "mender-gui": RepoName("mender-gui", "gui", "gui"),
    "mender-inventory": RepoName("mender-inventory", "inventory", "inventory"),
    "mender-useradm": RepoName("mender-useradm", "useradm", "useradm"),

    # These ones doesn't have a Docker name, but just use same as Git for
    # indexing purposes.
    "mender-artifact": RepoName("mender-artifact", "mender-artifact", "mender-artifact"),
    "mender-integration": RepoName("mender-integration", "integration", "integration"),
}

# Some convenient aliases, mainly because Git phrasing differs slightly from
# Docker.
REPO_ALIASES = {
    "api-gateway-docker": "mender-api-gateway",
    "deviceadm": "mender-device-adm",
    "deviceauth": "mender-device-auth",
    "mender": "mender-client",
    "mender-api-gateway-docker": "mender-api-gateway",
}

GIT_TO_BUILDPARAM_MAP = {
    "mender-api-gateway-docker": "API_GATEWAY_REV",
    "deployments": "DEPLOYMENTS_REV",
    "deviceadm": "DEVICEADM_REV",
    "deviceauth": "DEVICEAUTH_REV",
    "gui": "GUI_REV",
    "inventory": "INVENTORY_REV",
    "useradm": "USERADM_REV",

    "mender": "MENDER_REV",
    "mender-artifact": "ARTIFACTS_REV",

    "integration": "INTEGRATION_REV",
}

# These will be saved along with the state if they are changed.
EXTRA_BUILDPARAMS = {
    "META_MENDER_REV": "morty",
    "POKY_REV": "morty",
    "MENDER_QA_REV": "master",
    "BUILD_QEMU": "on",
    "TEST_QEMU": "on",
    "BUILD_BBB": "on",
    "TEST_BBB": "",
    "CLEAN_BUILD_CACHE": "",
    "UPLOAD_OUTPUT": "",
    "RUN_INTEGRATION_TESTS": "on",

    # "RELEASE_VERSION" will be added automatically.
}

def integration_dir():
    return os.path.join(os.path.dirname(sys.argv[0]), "..")

def ask(text):
    sys.stdout.write(text)
    sys.stdout.flush()
    reply = sys.stdin.readline().strip()
    # Make a separator before next information chunk.
    sys.stdout.write("\n")
    return reply

def deepupdate(original, update):
    """
    Recursively update a dict.
    Subdict's won't be overwritten but also updated.
    """
    for key, value in update.items():
        if key in original and isinstance(original[key], dict) and isinstance(value, dict):
            deepupdate(original[key], value)
        else:
            original[key] = value

def determine_repo(repoish):
    alias = REPO_ALIASES.get(repoish)
    if alias is not None:
        repoish = alias
    if not repoish.startswith("mender-"):
        repoish = "mender-" + repoish
    return REPOS[repoish]

def docker_compose_files_list(dir):
    """Return all docker-compose*.yml files in this directory."""
    list = []
    for entry in os.listdir(dir):
        if entry.startswith("docker-compose") and entry.endswith(".yml"):
            list.append(os.path.join(dir, entry))
    return list

def get_docker_compose_data(dir):
    """Return a structure of data from all the docker-compose YAML files."""
    data = {}
    for file in docker_compose_files_list(dir):
        fd = open(file)
        deepupdate(data, yaml.load(fd))
        fd.close()
    return data

def do_version_of(args):
    data = get_docker_compose_data(integration_dir())
    try:
        repo = determine_repo(args.version_of)
    except KeyError:
        print("Unrecognized repository: %s" % args.version_of)
        sys.exit(1)
    image = data['services'][repo.container]['image']
    print(image[(image.index(":") + 1):])

def state_value(state, key_list):
    """Gets a value from the state variable stored in the RELEASE_STATE yaml
    file. The key_list is a list of indexes, where each element represents a
    subkey of the previous key."""
    try:
        next = state
        for key in key_list:
            next = next[key]
        return next
    except KeyError:
        return None

def update_state(state, key_list, value):
    """Updates the state variable and writes this to the RELEASE_STATE state
    file. key_list is the same value as the state_value function."""
    next = state
    prev = state
    for key in key_list:
        prev = next
        if next.get(key) is None:
            next[key] = {}
        next = next[key]
    prev[key_list[-1]] = value

    fd = open(RELEASE_STATE, "w")
    fd.write(yaml.dump(state))
    fd.close()

def execute_git(state, repo_git, args, capture=False, capture_stderr=False):
    """Executes a Git command in the given repository, with args being a list
    of arguments (not including git itself)."""

    is_push = (args[0] == "push")
    is_change = (is_push
                 or (args[0] == "tag" and len(args) > 1)
                 or (args[0] == "config" and args[1] != "-l")
                 or (args[0] == "fetch")
                 or (args[0] == "reset")
                 or (args[0] == "commit"))

    if (not PUSH and is_push) or (DRY_RUN and is_change):
        print("Would have executed: cd %s && git %s"
              % (os.path.join(state['repo_dir'], repo_git), " ".join(args)))
        return None

    fd = os.open(".", flags=os.O_RDONLY)
    os.chdir(os.path.join(state['repo_dir'], repo_git))
    if capture_stderr:
        stderr = subprocess.STDOUT
    else:
        stderr = None

    try:
        if capture:
            output = subprocess.check_output(["git"] + args, stderr=stderr).decode().strip()
        else:
            output = None
            subprocess.check_call(["git"] + args, stderr=stderr)
    finally:
        os.fchdir(fd)
        os.close(fd)

    return output

def query_execute_git_list(execute_git_list):
    """Executes a list of Git commands after asking permission. The argument is
    a list of triplets with the first three arguments of execute_git. Both
    capture flags will be false during this call."""

    print("--------------------------------------------------------------------------------")
    for cmd in execute_git_list:
        # Provide quotes around arguments with spaces in them.
        print("cd %s && git %s" % (cmd[1], " ".join(['"%s"' % str if str.find(" ") >= 0 else str for str in cmd[2]])))
    reply = ask("\nOk to execute the above commands? ")
    if not reply.startswith("Y") and not reply.startswith("y"):
        return False

    for cmd in execute_git_list:
        execute_git(cmd[0], cmd[1], cmd[2])

    return True

def find_upstream_remote(state, repo_git):
    config = execute_git(state, repo_git, ["config", "-l"], capture=True)
    remote = None
    for line in config.split('\n'):
        match = re.match(r"^remote\.([^.]+)\.url=.*github\.com[/:]mendersoftware/%s(\.git)?$" % repo_git, line)
        if match is not None:
            remote = match.group(1)
            break

    if remote is None:
        raise Exception("Could not find git remote pointing to mendersoftware in %s" % repo_git)

    return remote

def refresh_repos(state):
    git_list = []

    for repo in REPOS.values():
        remote = find_upstream_remote(state, repo.git)
        git_list.append((state, repo.git, ["fetch", "--tags", remote,
                                           "+refs/heads/*:refs/remotes/%s/*" % remote]))

    query_execute_git_list(git_list)

def check_tag_availability(state):
    tag_avail = {}
    for repo in REPOS.values():
        tag_avail[repo.git] = {}
        try:
            execute_git(state, repo.git, ["rev-parse", state[repo.git]['version']],
                        capture=True, capture_stderr=True)
            tag_avail[repo.git]['already_released'] = True
            tag_avail[repo.git]['build_tag'] = state[repo.git]['version']
        except subprocess.CalledProcessError:
            tag_avail[repo.git]['already_released'] = False

            # Find highest <version>-buildX tag, where X is a number.
            tags = execute_git(state, repo.git, ["tag"], capture=True)
            highest = -1
            for tag in tags.split('\n'):
                match = re.match("^%s-build([0-9]+)$" % re.escape(state[repo.git]['version']), tag)
                if match is not None and int(match.group(1)) > highest:
                    highest = int(match.group(1))
                    highest_tag = tag
            if highest >= 0:
                tag_avail[repo.git]['build_tag'] = highest_tag

        if tag_avail[repo.git].get('build_tag') is not None:
            sha = execute_git(state, repo.git, ["rev-parse", "--short",
                                                tag_avail[repo.git]['build_tag'] + "~0"],
                              capture=True)
            tag_avail[repo.git]['sha'] = sha

    return tag_avail

def repo_sort_key(repo):
    return repo.git

def report_release_state(state, tag_avail):
    print("Mender release: %s" % state['version'])
    fmt_str = "%-25s %-10s %-18s %-20s"
    print(fmt_str % ("REPOSITORY", "VERSION", "PICK NEXT BUILD", "BUILD TAG"))
    print(fmt_str % ("", "", "TAG FROM", ""))
    for repo in sorted(REPOS.values(), key=repo_sort_key):
        if tag_avail[repo.git]['already_released']:
            built = state[repo.git]['version']
        else:
            built = tag_avail[repo.git].get('build_tag')
            if built is None:
                built = "<Needs a new build tag>"
            else:
                built = "%s (%s)" % (built, tag_avail[repo.git]['sha'])
        print(fmt_str % (repo.git, state[repo.git]['version'],
                         state[repo.git]['following'], built))

def annotation_version(repo, tag_avail):
    match = re.match("^(.*)-build([0-9]+)$", tag_avail[repo.git]['build_tag'])
    if match is None:
        return "%s version %s." % (repo.git, tag_avail[repo.git]['build_tag'])
    else:
        return "%s version %s Build %s." % (repo.git, match.group(1), match.group(2))

def generate_new_tags(state, tag_avail, final):
    """Creates new build tags, and returns the new tags in a modified
    tag_avail."""

    try:
        execute_git(state, "integration", ["diff-files", "--quiet"], capture=True)
    except subprocess.CalledProcessError:
        print("You cannot have uncommitted changes in integration when doing this operation")
        return tag_avail

    output = execute_git(state, "integration", ["show", "-s"], capture=True)
    if output.find(VERSION_BUMP_STRING) >= 0:
        # Previous version bump detected. Roll back one commit.
        execute_git(state, "integration", ["reset", "--hard", "HEAD~1"])

    # Find highest of all build tags in all repos.
    highest = 0
    for repo in REPOS.values():
        if not tag_avail[repo.git]['already_released'] and tag_avail[repo.git].get('build_tag') is not None:
            match = re.match(".*-build([0-9]+)$", tag_avail[repo.git]['build_tag'])
            if match is not None and int(match.group(1)) > highest:
                highest = int(match.group(1))

    # Assign new build tags to each repo based on our previous findings.
    next_tag_avail = copy.deepcopy(tag_avail)
    for repo in REPOS.values():
        if not tag_avail[repo.git]['already_released']:
            if final:
                # For final tag, point to the previous build tag, not the
                # version we follow.
                # "~0" is used to avoid a tag pointing to another tag. It should
                # point to the commit.
                sha = execute_git(state, repo.git, ["rev-parse", "--short",
                                                    tag_avail[repo.git]['build_tag'] + "~0"],
                                  capture=True)
                # For final tag, use actual version.
                next_tag_avail[repo.git]['build_tag'] = state[repo.git]['version']
            else:
                # "~0" is used to avoid a tag pointing to another tag. It should
                # point to the commit.
                sha = execute_git(state, repo.git, ["rev-parse", "--short",
                                                    state[repo.git]['following'] + "~0"],
                                  capture=True)
                # For non-final, use next build number.
                next_tag_avail[repo.git]['build_tag'] = "%s-build%d" % (state[repo.git]['version'], highest + 1)

            next_tag_avail[repo.git]['sha'] = sha

            print("-----------------------------------------------")
            if tag_avail[repo.git].get('build_tag') is None:
                # If there is no existing tag, just display latest commit.
                print("The latest commit in %s will be:" % repo.git)
                execute_git(state, repo.git, ["log", "-n1", sha])
            else:
                # If there is an existing tag, display range.
                print("The new commits in %s will be:" % repo.git)
                execute_git(state, repo.git, ["log", "%s..%s" % (tag_avail[repo.git]['build_tag'], sha)])
            print()

    if not final:
        print("Next build is build %d." % (highest + 1))
    print("Each repository's new tag will be:")
    report_release_state(state, next_tag_avail)

    reply = ask("Should each repository be tagged with this new build tag and pushed? ")
    if not reply.startswith("Y") and not reply.startswith("y"):
        return tag_avail

    reply = ask("Permission to edit and commit docker-compose.yml files to insert tags? ")
    if not reply.startswith("Y") and not reply.startswith("y"):
        return tag_avail

    for repo in REPOS.values():
        set_docker_compose_version_to(os.path.join(state['repo_dir'], "integration"),
                                      repo.docker,
                                      next_tag_avail[repo.git]['build_tag'])

    print("-----------------------------------------------")
    print("Changes to commit:")
    print()
    execute_git(state, "integration", ["diff"])
    git_list = []
    git_list.append((state, "integration",
                     ["commit", "-a", "-s", "-m", "%s %s.\n\nChangelog: None"
                      % (VERSION_BUMP_STRING, next_tag_avail["integration"]['build_tag'])]))

    if not query_execute_git_list(git_list):
        execute_git(state, "integration", ["reset", "--hard"])
        return tag_avail

    # Because of the commit above, integration repository now has a new sha.
    next_tag_avail["integration"]['sha'] = execute_git(state, "integration",
                                                       ["rev-parse", "--short",
                                                        state["integration"]['following'] + "~0"],
                                                       capture=True)
    # Now that we have the SHA, we can revert the integration branch.
    execute_git(state, "integration", ["reset", "--hard", "HEAD~1"])

    git_list = []
    for repo in REPOS.values():
        if not next_tag_avail[repo.git]['already_released']:
            git_list.append((state, repo.git, ["tag", "-a", "-m", annotation_version(repo, next_tag_avail),
                                               next_tag_avail[repo.git]['build_tag'],
                                               next_tag_avail[repo.git]['sha']]))
            remote = find_upstream_remote(state, repo.git)
            git_list.append((state, repo.git, ["push", remote, next_tag_avail[repo.git]['build_tag']]))

    if not query_execute_git_list(git_list):
        return tag_avail

    for repo in REPOS.values():
        if not next_tag_avail[repo.git]['already_released'] and final:
            if repo.git != "integration":
                update_state(state, [repo.git, 'following'], next_tag_avail[repo.git]['build_tag'])
            next_tag_avail[repo.git]['already_released'] = True

    return next_tag_avail

def trigger_jenkins_build(state, tag_avail):
    try:
        import requests
    except ImportError:
        print("PyYAML missing, try running 'sudo pip3 install requests'.")
        sys.exit(2)

    params = copy.deepcopy(state['extra_buildparams'])

    postdata = []
    for repo in sorted(REPOS.values(), key=repo_sort_key):
        if tag_avail[repo.git].get('build_tag') is None:
            print("One of the repositories doesn't have a build tag yet!")
            return
        params[GIT_TO_BUILDPARAM_MAP[repo.git]] = tag_avail[repo.git]['build_tag']

    params['RELEASE_VERSION'] = state['version']

    while True:
        print("--------------------------------------------------------------------------------")
        fmt_str = "%-20s %-20s"
        print(fmt_str % ("Build parameter", "Value"))
        for param in sorted(params.keys()):
            print(fmt_str % (param, params[param]))

        reply = ask("Will trigger a build with these values, ok? ")
        if reply.startswith("Y") or reply.startswith("y"):
            break

        reply = ask("Do you want to change any of the parameters? ")
        if not reply.startswith("Y") and not reply.startswith("y"):
            return

        name = ask("Which one? ")
        if params.get(name) is None:
            print("Parameter not found!")
            continue
        params[name] = ask("Ok. New value? ")

        if EXTRA_BUILDPARAMS.get(name) is not None:
            # Save extra build parameters persistently.
            update_state(state, ['extra_buildparams', name], params[name])

    # Order is important here, because Jenkins passes in the same parameters
    # multiple times, as pairs that complete each other.
    # Jenkins additionally needs the input as json as well, so create that from
    # above parameters.
    postdata = []
    jdata = { "parameter": [] }
    for param in params.items():
        postdata.append(("name", param[0]))
        if param[1] != "":
            postdata.append(("value", param[1]))

        if param[1] == "on":
            jdata['parameter'].append({"name": param[0], "value": True})
        elif param[1] == "":
            jdata['parameter'].append({"name": param[0], "value": False})
        else:
            jdata['parameter'].append({"name": param[0], "value": param[1]})

    try:
        reply = requests.get("%s/%s" % (JENKINS_SERVER, JENKINS_CRUMB_ISSUER),
                             data=postdata)
        if reply.status_code < 200 or reply.status_code >= 300:
            print("Crumb request FAILED and returned: %d: %s" % (reply.status_code, reply.reason))
            return
        crumb = reply.content.decode().split(':', 2)
        postdata.append(("statusCode", "303"))
        jdata["statusCode"] = "303"
        postdata.append(("redirectTo", "."))
        jdata["redirectTo"] = "."
        postdata.append((crumb[0], crumb[1]))
        jdata[crumb[0]] = crumb[1]
        postdata.append(("json", json.dumps(jdata)))

        reply = requests.post("%s/%s/build?delay=0sec" % (JENKINS_SERVER, JENKINS_JOB),
                              data=postdata)
        if reply.status_code < 200 or reply.status_code >= 300:
            print("Request returned: %d: %s" % (reply.status_code, reply.reason))
        else:
            print("Build started.")
            match = re.search('href="(/%s/[0-9]+/)"' % JENKINS_JOB, reply.content.decode())
            if match is not None:
                print("Link: %s%s" % (JENKINS_SERVER, match.group(1)))
            else:
                print("Unable to determine build number.")
    except Exception:
        print("Failed to start build:")
        traceback.print_exc()

def set_docker_compose_version_to(dir, repo_docker, tag):
    compose_files = docker_compose_files_list(dir)
    for file in compose_files:
        old = open(file)
        new = open(file + ".tmp", "w")
        for line in old:
            # Replace build tag with a new one.
            line = re.sub(r"^(\s*image:\s*mendersoftware/%s:)\S+(\s*)$" % re.escape(repo_docker),
                          r"\g<1>%s\2" % tag, line)
            new.write(line)
        new.close()
        old.close()
        os.rename(file + ".tmp", file)

def purge_build_tags(state, tag_avail):
    git_list = []
    for repo in REPOS.values():
        remote = find_upstream_remote(state, repo.git)
        tag_list = execute_git(state, repo.git, ["tag"], capture=True).split('\n')
        to_purge = []
        for tag in tag_list:
            if re.match('^%s-build[0-9]+$' % re.escape(state[repo.git]['version']), tag):
                to_purge.append(tag)
        if len(to_purge) > 0:
            git_list.append((state, repo.git, ["tag", "-d"] + to_purge))
            git_list.append((state, repo.git, ["push", remote] + [":%s" % tag for tag in to_purge]))

    query_execute_git_list(git_list)

def switch_following_branch(state, tag_avail):
    current = None
    for repo in REPOS.values():
        if repo.git == "integration":
            # integration is special. Because we need to commit changes to its
            # docker-compose files, we have to follow HEAD.
            continue
        if not tag_avail[repo.git]['already_released']:
            if current is None:
                # Pick first match as current state.
                current = state[repo.git]['following']
            if current == 'HEAD':
                assign_default_following_branch(state, repo)
            else:
                update_state(state, [repo.git, 'following'], "HEAD")

def assign_default_following_branch(state, repo):
    remote = find_upstream_remote(state, repo.git)
    if repo.git == "integration":
        # integration is special. Because we need to commit changes to its
        # docker-compose files, we have to follow HEAD.
        update_state(state, [repo.git, 'following'], "HEAD")
    else:
        branch = re.sub("[0-9]+$", "x", state[repo.git]['version'])
        update_state(state, [repo.git, 'following'], "%s/%s" % (remote, branch))

def do_release():
    if os.path.exists(RELEASE_STATE):
        while True:
            reply = ask("Release already in progress. Continue or start a new one [C/S]? ")
            if reply == "C" or reply == "c":
                new_release = False
            elif reply == "S" or reply == "s":
                new_release = True
            else:
                print("Must answer C or S.")
                continue
            break
    else:
        print("No existing release in progress, starting new one...")
        new_release = True

    if new_release:
        state = {}
    else:
        print("Loading existing release state data...")
        print("Note that you can always edit or delete %s manually" % RELEASE_STATE)
        fd = open(RELEASE_STATE)
        state = yaml.load(fd)
        fd.close()

    if state_value(state, ['repo_dir']) is None:
        reply = ask("Which directory contains all the Git repositories? ")
        reply = re.sub("~", os.environ['HOME'], reply)
        update_state(state, ['repo_dir'], reply)

    if state_value(state, ['version']) is None:
        update_state(state, ['version'], ask("Which release of Mender will this be? "))

    update_state(state, ["integration", 'version'], state['version'])

    for repo in REPOS.values():
        if state_value(state, [repo.git, 'version']) is None:
            update_state(state, [repo.git, 'version'],
                         ask("What version of %s should be included? " % repo.git))

    input = ask("Do you want to fetch all the latest tags and branches in all repositories (will not change checked-out branch)? ")
    if input.startswith("Y") or input.startswith("y"):
        refresh_repos(state)

    tag_avail = check_tag_availability(state)

    for repo in REPOS.values():
        if tag_avail[repo.git]['already_released']:
            update_state(state, [repo.git, 'following'], state[repo.git]['version'])
        else:
            # Follow "1.0.x" style branches by default.
            assign_default_following_branch(state, repo)

    for param in EXTRA_BUILDPARAMS.keys():
        if state_value(state, ["extra_buildparams", param]) is None:
            update_state(state, ["extra_buildparams", param], EXTRA_BUILDPARAMS[param])

    first_time = True
    while True:
        if first_time:
            first_time = False
        else:
            # Provide a break to see output from what was just done.
            ask("Press Enter... ")

        print("--------------------------------------------------------------------------------")
        print("Current state of release:")
        report_release_state(state, tag_avail)

        print("What do you want to do?")
        print("-- Main operations")
        print("  T) Generate and push new build tags")
        print("  B) Trigger new Jenkins build using current tags")
        print("  F) Tag and push final tag, based on previous build tag")
        print("  Q) Quit (your state is saved in %s)" % RELEASE_STATE)
        print()
        print("-- Less common operations")
        print("  P) Push current build tags (not necessary unless -s was used before)")
        print("  U) Purge build tags from all repositories")
        print("  S) Switch fetching branch between remote and local branch (affects next")
        print("       tagging)")

        reply = ask("Choice? ")

        if reply == "Q" or reply == "q":
            break
        elif reply == "T" or reply == "t":
            tag_avail = generate_new_tags(state, tag_avail, final=False)
        elif reply == "F" or reply == "f":
            tag_avail = generate_new_tags(state, tag_avail, final=True)
            print()
            reply = ask("Purge all build tags from all repositories (recommended)? ")
            if reply == "Y" or reply == "y":
                purge_build_tags(state, tag_avail)
        elif reply == "P" or reply == "p":
            git_list = []
            for repo in REPOS.values():
                if not tag_avail[repo.git]['already_released']:
                    remote = find_upstream_remote(state, repo.git)
                    git_list.append((state, repo.git, ["push", remote, tag_avail[repo.git]['build_tag']]))
            query_execute_git_list(git_list)
        elif reply == "B" or reply == "b":
            trigger_jenkins_build(state, tag_avail)
        elif reply == "U" or reply == "u":
            purge_build_tags(state, tag_avail)
        elif reply == "S" or reply == "s":
            switch_following_branch(state, tag_avail)
        else:
            print("Invalid choice!")

def do_set_version_to(args):
    if args.version is None:
        print("--set-version-of requires --version")
        sys.exit(1)

    repo = determine_repo(args.set_version_of)
    set_docker_compose_version_to(integration_dir(), repo.docker, args.version)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version-of", dest="version_of", metavar="SERVICE",
                        help="Determine version of given service")
    parser.add_argument("--set-version-of", dest="set_version_of", metavar="SERVICE",
                        help="Write version of given service into docker-compose.yml")
    parser.add_argument("--version", dest="version",
                        help="Version to write using previous option")
    parser.add_argument("--release", action="store_true",
                        help="Start the release process (interactive)")
    parser.add_argument("-s", "--simulate-push", action="store_true",
                        help="Simulate (don't do) pushes")
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help="Don't take any action at all")
    args = parser.parse_args()

    # Check conflicting options.
    operations = 0
    for operation in [args.version_of, args.release, args.set_version_of]:
        if operation:
            operations = operations + 1
    if operations > 1:
        print("--version-of, --set-version-of and --release are mutually exclusive!")
        sys.exit(1)

    if args.simulate_push:
        global PUSH
        PUSH = False
    if args.dry_run:
        global DRY_RUN
        DRY_RUN = True

    if args.version_of is not None:
        do_version_of(args)
    elif args.set_version_of is not None:
        do_set_version_to(args)
    elif args.release:
        do_release()
    else:
        parser.print_help()
        sys.exit(1)

main()
