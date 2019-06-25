#!/usr/bin/env python3

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
import logging

try:
    import yaml
except ImportError:
    print("PyYAML missing, try running 'sudo pip3 install pyyaml'.")
    sys.exit(2)

# Disable pager during menu navigation.
os.environ['GIT_PAGER'] = "cat"

# This is basically a YAML file which contains the state of the release tool.
# The easiest way to understand its format is by just looking at it after the
# key fields have been filled in. This is updated continuously while the script
# is operating.
# The repositories are indexed by their Git repository names.
RELEASE_TOOL_STATE = None

JENKINS_SERVER = "https://mender-jenkins.mender.io"
JENKINS_JOB = "job/mender-builder"
JENKINS_USER = None
JENKINS_PASSWORD = None
JENKINS_CREDS_MISSING_ERR = """Jenkins credentials not found. Possible locations:
- JENKINS_USER / JENKINS_PASSWORD environment variables
- 'pass' password management storage."""

# What we use in commits messages when bumping versions.
VERSION_BUMP_STRING = "Bump versions for Mender"

# Whether or not pushes should really happen.
PUSH = True
# Whether this is a dry-run.
DRY_RUN = False

class Component:
    # A map that lists all our git repositories, docker images, and docker
    # container names, and how they are associated to one another. When you add
    # something to this list, make sure to add it to all three sections: "git",
    # "docker_image" and "docker_container". Binary tools that don't have Docker
    # components, will only have the "git" part.
    COMPONENT_MAPS = {
        "git": {
            "deployments": {
                "docker_image": ["deployments"],
                "docker_container": ["mender-deployments"],
                "release_component": True,
            },
            "deviceadm": {
                "docker_image": ["deviceadm"],
                "docker_container": ["mender-device-adm"],
                "release_component": False,
            },
            "deviceauth": {
                "docker_image": ["deviceauth"],
                "docker_container": ["mender-device-auth"],
                "release_component": True,
            },
            "gui": {
                "docker_image": ["gui"],
                "docker_container": ["mender-gui"],
                "release_component": True,
            },
            "integration": {
                "docker_image": [],
                "docker_container": [],
                "release_component": True,
            },
            "inventory": {
                "docker_image": ["inventory"],
                "docker_container": ["mender-inventory"],
                "release_component": True,
            },
            "mender": {
                "docker_image": ["mender-client-qemu", "mender-client-docker", "mender-client-qemu-rofs"],
                "docker_container": ["mender-client"],
                "release_component": True,
            },
            "mender-api-gateway-docker": {
                "docker_image": ["api-gateway"],
                "docker_container": ["mender-api-gateway"],
                "release_component": True,
            },
            "mender-artifact": {
                "docker_image": [],
                "docker_container": [],
                "release_component": True,
            },
            "mender-cli": {
                "docker_image": [],
                "docker_container": [],
                "release_component": True,
            },
            "mender-conductor": {
                "docker_image": ["mender-conductor", "email-sender"],
                "docker_container": ["mender-conductor", "mender-email-sender"],
                "release_component": True,
            },
            "mender-conductor-enterprise": {
                "docker_image": ["mender-conductor-enterprise"],
                "docker_container": ["mender-conductor"],
                "release_component": True,
            },
            "tenantadm": {
                "docker_image": ["tenantadm"],
                "docker_container": ["mender-tenantadm"],
                "release_component": False,
            },
            "useradm": {
                "docker_image": ["useradm"],
                "docker_container": ["mender-useradm"],
                "release_component": True,
            },
        },
        "docker_image": {
            "deployments": {
                "git": ["deployments"],
                "docker_container": ["mender-deployments"],
                "release_component": True,
            },
            "deviceadm": {
                "git": ["deviceadm"],
                "docker_container": ["mender-device-adm"],
                "release_component": False,
            },
            "deviceauth": {
                "git": ["deviceauth"],
                "docker_container": ["mender-device-auth"],
                "release_component": True,
            },
            "gui": {
                "git": ["gui"],
                "docker_container": ["mender-gui"],
                "release_component": True,
            },
            "inventory": {
                "git": ["inventory"],
                "docker_container": ["mender-inventory"],
                "release_component": True,
            },
            "mender-client-docker": {
                "git": ["mender"],
                "docker_container": ["mender-client"],
                "release_component": True,
            },
            "mender-client-qemu": {
                "git": ["mender"],
                "docker_container": ["mender-client"],
                "release_component": True,
            },
            "mender-client-qemu-rofs": {
                "git": ["mender"],
                "docker_container": ["mender-client"],
                "release_component": True,
            },
            "api-gateway": {
                "git": ["mender-api-gateway-docker"],
                "docker_container": ["mender-api-gateway"],
                "release_component": True,
            },
            "mender-conductor": {
                "git": ["mender-conductor"],
                "docker_container": ["mender-conductor"],
                "release_component": True,
            },
            "email-sender": {
                "git": ["mender-conductor"],
                "docker_container": ["mender-email-sender"],
                "release_component": True,
            },
            "mender-conductor-enterprise": {
                "git": ["mender-conductor-enterprise"],
                "docker_container": ["mender-conductor"],
                "release_component": True,
            },
            "tenantadm": {
                "git": ["tenantadm"],
                "docker_container": ["mender-tenantadm"],
                "release_component": False,
            },
            "useradm": {
                "git": ["useradm"],
                "docker_container": ["mender-useradm"],
                "release_component": True,
            },
        },
        "docker_container": {
            "mender-deployments": {
                "git": ["deployments"],
                "docker_image": ["deployments"],
                "release_component": True,
            },
            "mender-device-auth": {
                "git": ["deviceauth"],
                "docker_image": ["deviceauth"],
                "release_component": True,
            },
            "mender-device-adm": {
                "git": ["deviceadm"],
                "docker_image": ["deviceadm"],
                "release_component": False,
            },
            "mender-gui": {
                "git": ["gui"],
                "docker_image": ["gui"],
                "release_component": True,
            },
            "mender-inventory": {
                "git": ["inventory"],
                "docker_image": ["inventory"],
                "release_component": True,
            },
            "mender-client": {
                "git": ["mender"],
                "docker_image": ["mender-client-qemu", "mender-client-docker", "mender-client-qemu-rofs"],
                "release_component": True,
            },
            "mender-api-gateway": {
                "git": ["mender-api-gateway-docker"],
                "docker_image": ["api-gateway"],
                "release_component": True,
            },
            "mender-conductor": {
                "git": ["mender-conductor", "mender-conductor-enterprise"],
                "docker_image": ["mender-conductor", "mender-conductor-enterprise"],
                "release_component": True,
            },
            "mender-email-sender": {
                "git": ["mender-conductor"],
                "docker_image": ["email-sender"],
                "release_component": True,
            },
            "mender-tenantadm": {
                "git": ["tenantadm"],
                "docker_image": ["tenantadm"],
                "release_component": False,
            },
            "mender-useradm": {
                "git": ["useradm"],
                "docker_image": ["useradm"],
                "release_component": True,
            },
        },
    }

    name = None
    type = None
    def __init__(self, name, type):
        self.name = name
        self.type = type

    def git(self):
        if self.type != "git":
            raise Exception("Tried to get git name from non-git component")
        return self.name
    def docker_container(self):
        if self.type != "docker_container":
            raise Exception("Tried to get docker_container name from non-docker_container component")
        return self.name
    def docker_image(self):
        if self.type != "docker_image":
            raise Exception("Tried to get docker_image name from non-docker_image component")
        return self.name
    def yml(self):
        if self.type != "yml":
            raise Exception("Tried to get yml name from non-yml component")
        return self.name

    @staticmethod
    def get_component_of_type(type, name):
        if Component.COMPONENT_MAPS[type].get(name) is None:
            raise KeyError("Component '%s' of type %s not found" % (name, type))
        return Component(name, type)

    @staticmethod
    def get_component_of_any_type(name):
        for type in ["git", "docker_image", "docker_container"]:
            try:
                return Component.get_component_of_type(type, name)
            except KeyError:
                continue
        raise KeyError("Component '%s' not found" % name)

    @staticmethod
    def get_components_of_type(type, only_release=None, only_non_release=False):
        if only_release is None:
            if only_non_release:
                only_release = False
            else:
                only_release = True
        if only_release and only_non_release:
            raise Exception("only_release and only_non_release can't both be true")
        components = []
        for comp in Component.COMPONENT_MAPS[type]:
            if Component.COMPONENT_MAPS[type][comp]["release_component"]:
                if only_non_release:
                    continue
            else:
                if only_release:
                    continue
            components.append(Component(comp, type))
        return components

    def associated_components_of_type(self, type):
        """Returns all components of type `type` that are associated with self."""

        if type == self.type:
            return [Component(self.name, self.type)]

        try:
            comps = []
            for name in Component.COMPONENT_MAPS[self.type][self.name][type]:
                comps.append(Component(name, type))
            return comps
        except KeyError:
            raise KeyError("No such combination: Component '%s' of type %s doesn't have any associated components of type %s"
                           % (self.name, self.type, type))

    def yml_components(self):
        """Returns the name of the service in our YML docker-compose files. This is
        usually the same as the docker_image name, but for services that don't
        have Docker images, it will be the git name, which is what is used in
        the other-components.yml file."""

        comps = self.associated_components_of_type("docker_image")
        if len(comps) == 0:
            # For the fake services that don't have Docker images, but reside in
            # other-components.yml.
            comps = self.associated_components_of_type("git")
        for comp in comps:
            comp.type = "yml"
        return comps


# A map from git repo name to build parameter name in Jenkins.
GIT_TO_BUILDPARAM_MAP = {
    "mender-api-gateway-docker": "MENDER_API_GATEWAY_DOCKER_REV",
    "mender-conductor": "MENDER_CONDUCTOR_REV",
    "mender-conductor-enterprise": "MENDER_CONDUCTOR_ENTERPRISE_REV",
    "deployments": "DEPLOYMENTS_REV",
    "deviceauth": "DEVICEAUTH_REV",
    "gui": "GUI_REV",
    "inventory": "INVENTORY_REV",
    "useradm": "USERADM_REV",

    "mender": "MENDER_REV",
    "mender-artifact": "MENDER_ARTIFACT_REV",
    "mender-cli": "MENDER_CLI_REV",
    "meta-mender": "META_MENDER_REV",

    "integration": "INTEGRATION_REV",

    "mender-qa": "MENDER_QA_REV",
}

class JenkinsParam:
    type = None
    value = None

    def __init__(self, type, value):
        self.type = type
        self.value = value

EXTRA_BUILDPARAMS_CACHE = None

def print_line():
    print("--------------------------------------------------------------------------------")

def init_jenkins_creds():
    global JENKINS_USER
    global JENKINS_PASSWORD
    JENKINS_USER = os.getenv("JENKINS_USER")
    JENKINS_PASSWORD = os.getenv("JENKINS_PASSWORD")

    if JENKINS_USER is not None and JENKINS_PASSWORD is not None:
        return

    try:
        server = JENKINS_SERVER
        if server.startswith("https://"):
            server = server[len("https://"):]

        output = subprocess.check_output(["pass", "find", server]).decode()
        count = 0
        for line in output.split('\n'):
            if line.startswith("Search terms: "):
                continue
            count += 1
        if count == 0:
            return

        print("Attempting to fetch Jenkins credentials from 'pass'...")

        output = subprocess.check_output(["pass", "show", server]).decode()
        line_no = 0
        for line in output.split('\n'):
            line_no += 1

            if line_no == 1:
                JENKINS_PASSWORD = line
                continue

            if line.find(":") < 0:
                continue

            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key in ["login", "user", "username"]:
                JENKINS_USER = value

    except (subprocess.CalledProcessError, FileNotFoundError):
        return

def integration_dir():
    """Return the location of the integration repository."""

    if os.path.isabs(sys.argv[0]):
        return os.path.normpath(os.path.dirname(os.path.dirname(sys.argv[0])))
    else:
        return os.path.normpath(os.path.join(os.getcwd(), os.path.dirname(sys.argv[0]), ".."))

def ask(text):
    """Ask a question and return the reply."""

    sys.stdout.write(text)
    sys.stdout.flush()
    reply = sys.stdin.readline().strip()
    # Make a separator before next information chunk.
    sys.stdout.write("\n")
    return reply

def docker_compose_files_list(dir):
    """Return all docker-compose*.yml files in given directory."""
    list = []
    for entry in os.listdir(dir):
        if (entry == "other-components.yml"
            or (entry.startswith("docker-compose") and entry.endswith(".yml"))):
            list.append(os.path.join(dir, entry))
    return list

def get_docker_compose_data_from_json_list(json_list):
    """Return the Yaml as a simplified structure from the json list:
    {
        image_name: {
            "container": container_name,
            "version": version,
        }
    }
    """
    data = {}
    for json_str in json_list:
        json_elem = yaml.load(json_str)
        for container, cont_info in json_elem['services'].items():
            image = cont_info.get('image')
            if image is None or "mendersoftware/" not in image:
                continue
            image_and_ver = image.split("/", 1)[1].split(":", 1)
            if data.get(image_and_ver[0]) is not None:
                raise Exception(("More than one container is using the image name '%s'. "
                                 + "The tool currently does not support this.")
                                % image_and_ver[0])
            data[image_and_ver[0]] = {
                "container": container,
                "version": image_and_ver[1]
            }
    return data

def get_docker_compose_data(dir):
    """Return docker-compose data from all the YML files in the directory.
    See get_docker_compose_data_from_json_list."""
    json_list = []
    for filename in docker_compose_files_list(dir):
        with open(filename) as fd:
            json_list.append(fd.read())

    return get_docker_compose_data_from_json_list(json_list)

def get_docker_compose_data_for_rev(git_dir, rev):
    """Return docker-compose data from all the YML files in the given revision.
    See get_docker_compose_data_from_json_list."""
    yamls = []
    files = execute_git(None, git_dir, ["ls-tree", "--name-only", rev],
                        capture=True).strip().split('\n')
    for filename in files:
        if (filename != "other-components.yml"
            and not (filename.startswith("docker-compose") and filename.endswith(".yml"))):
            continue

        output = execute_git(None, git_dir, ["show", "%s:%s" % (rev, filename)],
                             capture=True)
        yamls.append(output)

    return get_docker_compose_data_from_json_list(yamls)

def version_of(integration_dir, yml_component, in_integration_version=None):
    if yml_component.yml() == "integration":
        if in_integration_version is not None:
            # Just return the supplied version string.
            return in_integration_version
        else:
            # Return "closest" branch or tag name. Basically we measure the
            # distance in commits from the merge base of most refs to the
            # current HEAD, and then pick the shortest one, and we assume that
            # this is our current version. We pick all the refs from tags and
            # local branches, as well as single level upstream branches (which
            # avoids pull requests).
            return subprocess.check_output("""
                for i in $(git for-each-ref --format='%(refname:short)' 'refs/tags/*' 'refs/heads/*' 'refs/remotes/*/*'); do
                    echo $(git log --oneline $(git merge-base $i HEAD)..HEAD | wc -l) $i
                done | sort -n | head -n1 | awk '{print $2}'
            """, shell=True, cwd=integration_dir).strip().decode()

    if in_integration_version is not None:
        # Check if there is a range, and if so, return range.
        range_type = ""
        rev_range = in_integration_version.split("...")
        if len(rev_range) > 1:
            range_type = "..."
        else:
            rev_range = in_integration_version.split("..")
            if len(rev_range) > 1:
                range_type = ".."
        repo_range = []
        for rev in rev_range:
            match = re.match("^(.*/)", rev)
            if match is not None:
                remote = match.group(1)
            else:
                remote = ""
            data = get_docker_compose_data_for_rev(integration_dir, rev)
            # If the repository didn't exist in that version, just return all
            # commits in that case, IOW no lower end point range.
            if data.get(yml_component.yml()) is not None:
                repo_range.append(remote + data[yml_component.yml()]['version'])
        return range_type.join(repo_range)
    else:
        data = get_docker_compose_data(integration_dir)
        return data[yml_component.yml()]['version']

def do_version_of(args):
    """Process --version-of argument."""

    try:
        comp = Component.get_component_of_any_type(args.version_of)
    except KeyError:
        print("Unrecognized repository: %s" % args.version_of)
        sys.exit(1)

    yml_component = comp.yml_components()[0]

    print(version_of(integration_dir(), yml_component, args.in_integration_version))

def do_list_repos(args, optional_too):
    """Lists the repos, using the provided type."""

    cli_types = {
        "container": "docker_container",
        "docker": "docker_image",
        "git": "git",
    }
    assert args.list in cli_types, "%s is not a valid name type!" % args.list
    type = cli_types[args.list]

    repos = [comp.name for comp in Component.get_components_of_type(type, only_release=(not optional_too))]

    for repo in sorted(repos):
        print(repo)

def version_sort_key(version):
    """Returns a key used to compare versions."""

    components = version.split(".")
    assert len(components) == 3, "Invalid version passed to version_sort_key"
    major, minor = [int(components[0]), int(components[1])]
    patch_and_beta = components[2].split("b")
    assert len(patch_and_beta) in [1, 2], "Invalid patch/beta component"
    patch = int(patch_and_beta[0])
    if len(patch_and_beta) == 2:
        beta = int(patch_and_beta[1])
    else:
        # Just for comparison purposes: rate high.
        beta = 99
    return "%02d%02d%02d%02d" % (major, minor, patch, beta)

def sorted_final_version_list(git_dir):
    """Returns a sorted list of all final version tags."""

    tags = execute_git(None, git_dir, ["for-each-ref", "--format=%(refname:short)",
                                       # Two digits for each component ought to be enough...
                                       "refs/tags/[0-9].[0-9].[0-9]",
                                       "refs/tags/[0-9].[0-9].[0-9][0-9]",
                                       "refs/tags/[0-9].[0-9][0-9].[0-9]",
                                       "refs/tags/[0-9].[0-9][0-9].[0-9][0-9]",
                                       "refs/tags/[0-9][0-9].[0-9].[0-9]",
                                       "refs/tags/[0-9][0-9].[0-9].[0-9][0-9]",
                                       "refs/tags/[0-9][0-9].[0-9][0-9].[0-9]",
                                       "refs/tags/[0-9][0-9].[0-9][0-9].[0-9][0-9]",
                                       "refs/tags/[0-9].[0-9].[0-9]b[0-9]",
                                       "refs/tags/[0-9].[0-9].[0-9][0-9]b[0-9]",
                                       "refs/tags/[0-9].[0-9][0-9].[0-9]b[0-9]",
                                       "refs/tags/[0-9].[0-9][0-9].[0-9][0-9]b[0-9]",
                                       "refs/tags/[0-9][0-9].[0-9].[0-9]b[0-9]",
                                       "refs/tags/[0-9][0-9].[0-9].[0-9][0-9]b[0-9]",
                                       "refs/tags/[0-9][0-9].[0-9][0-9].[0-9]b[0-9]",
                                       "refs/tags/[0-9][0-9].[0-9][0-9].[0-9][0-9]b[0-9]"],
                       capture=True)
    return sorted(tags.split(), key=version_sort_key, reverse=True)

def state_value(state, key_list):
    """Gets a value from the state variable stored in the RELEASE_TOOL_STATE yaml
    file. The key_list is a list of indexes, where each element represents a
    subkey of the previous key.

    The difference between this function and simply indexing 'state' directly is
    that if any subkey is not found, including parent keys, None is returned
    instead of exception.
    """

    try:
        next = state
        for key in key_list:
            next = next[key]
        return next
    except KeyError:
        return None

def update_state(state, key_list, value):
    """Updates the state variable and writes this to the RELEASE_TOOL_STATE state
    file. key_list is the same value as the state_value function."""
    next = state
    prev = state
    for key in key_list:
        prev = next
        if next.get(key) is None:
            next[key] = {}
        next = next[key]
    prev[key_list[-1]] = value

    fd = open(RELEASE_TOOL_STATE, "w")
    fd.write(yaml.dump(state))
    fd.close()

def execute_git(state, repo_git, args, capture=False, capture_stderr=False):
    """Executes a Git command in the given repository, with args being a list
    of arguments (not including git itself). capture and capture_stderr
    arguments causes it to return stdout or stdout+stderr as a string.

    state can be None, but if so, then repo_git needs to be an absolute path.

    The function automatically takes into account Git commands with side effects
    and applies push simulation and dry run if those are enabled."""

    is_push = (args[0] == "push")
    is_change = (is_push
                 or (args[0] == "tag" and len(args) > 1)
                 or (args[0] == "branch" and len(args) > 1)
                 or (args[0] == "config" and args[1] != "-l")
                 or (args[0] == "checkout")
                 or (args[0] == "commit")
                 or (args[0] == "fetch")
                 or (args[0] == "init")
                 or (args[0] == "reset"))

    if os.path.isabs(repo_git):
        git_dir = repo_git
    else:
        git_dir = os.path.join(state['repo_dir'], repo_git)

    if (not PUSH and is_push) or (DRY_RUN and is_change):
        print("Would have executed: cd %s && git %s"
              % (git_dir, " ".join(args)))
        return None

    fd = os.open(".", flags=os.O_RDONLY)
    os.chdir(git_dir)
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

    print_line()
    for cmd in execute_git_list:
        # Provide quotes around arguments with spaces in them.
        print("cd %s && git %s" % (cmd[1], " ".join(['"%s"' % str if str.find(" ") >= 0 else str for str in cmd[2]])))
    reply = ask("\nOk to execute the above commands? ")
    if not reply.startswith("Y") and not reply.startswith("y"):
        return False

    for cmd in execute_git_list:
        execute_git(cmd[0], cmd[1], cmd[2])

    return True

def query_execute_list(execute_list):
    """Executes the list of commands after asking first. The argument is a list of
    lists, where the inner list is the argument to subprocess.check_call.

    The function automatically takes into account Docker commands with side
    effects and applies push simulation and dry run if those are enabled.
    """

    print_line()
    for cmd in execute_list:
        # Provide quotes around arguments with spaces in them.
        print(" ".join(['"%s"' % str if str.find(" ") >= 0 else str for str in cmd]))
    reply = ask("\nOk to execute the above commands? ")
    if not reply.startswith("Y") and not reply.startswith("y"):
        return False

    for cmd in execute_list:
        is_push = cmd[0] == "docker" and cmd[1] == "push"
        is_change = is_push or (
            cmd[0] == "docker" and cmd[1] == "tag")
        if (not PUSH and is_push) or (DRY_RUN and is_change):
            print("Would have executed: %s" % " ".join(cmd))
            continue

        subprocess.check_call(cmd)

    return True

def setup_temp_git_checkout(state, repo_git, ref):
    """Checks out a temporary Git directory, and returns an absolute path to
    it. Checks out the ref specified in ref."""

    tmpdir = os.path.join(state['repo_dir'], "tmp_checkout", repo_git)
    cleanup_temp_git_checkout(tmpdir)
    os.makedirs(tmpdir)

    if not os.path.exists(os.path.join(state['repo_dir'], repo_git)):
        raise Exception("%s does not exist in %s!" % (repo_git, state['repo_dir']))

    if ref.find('/') < 0:
        # Local branch.
        checkout_cmd = ["checkout"]
    else:
        # Remote branch.
        checkout_cmd = ["checkout", "-t"]

    try:
        output = execute_git(state, tmpdir, ["init"], capture=True, capture_stderr=True)
        output = execute_git(state, tmpdir, ["fetch", os.path.join(state['repo_dir'], repo_git),
                                    "--tags"], capture=True, capture_stderr=True)
        output = execute_git(state, tmpdir, ["tag"], capture=True)
        tags = output.split('\n')
        output = execute_git(state, tmpdir, ["branch"], capture=True)
        branches = output.split('\n')
        if ref not in tags and ref not in branches:
            # Try to mirror all branches locally instead of just as remote branches.
            output = execute_git(state, tmpdir, ["fetch", os.path.join(state['repo_dir'], repo_git),
                                                 "--tags", "%s:%s" % (ref, ref)], capture=True,
                                 capture_stderr=True)
        output = execute_git(state, tmpdir, checkout_cmd + [ref], capture=True, capture_stderr=True)
    except:
        print("Output from previous Git command: %s" % output)
        raise

    return tmpdir

def cleanup_temp_git_checkout(tmpdir):
    shutil.rmtree(tmpdir, ignore_errors=True)

def find_upstream_remote(state, repo_git):
    """Given a Git repository name, figure out which remote name is the
    "mendersoftware" upstream."""

    config = execute_git(state, repo_git, ["config", "-l"], capture=True)
    remote = None
    for line in config.split('\n'):
        match = re.match(r"^remote\.([^.]+)\.url=.*github\.com[/:]mendersoftware/%s(\.git)?$"
                         % os.path.basename(repo_git), line)
        if match is not None:
            remote = match.group(1)
            break

    if remote is None:
        raise Exception("Could not find git remote pointing to mendersoftware in %s" % repo_git)

    return remote

def refresh_repos(state):
    """Do a full 'git fetch' on all repositories."""

    git_list = []

    for repo in Component.get_components_of_type("git"):
        remote = find_upstream_remote(state, repo.git())
        git_list.append((state, repo.git(), ["fetch", "--tags", remote,
                                             "+refs/heads/*:refs/remotes/%s/*" % remote]))

    query_execute_git_list(git_list)

def check_tag_availability(state):
    """Check which tags are available in all the Git repositories, and return
    this as the tag_avail data structure.

    The main fields in this one are:
      <repo>:
        already_released: <whether this is a final release tag or not (true/false)>
        build_tag: <highest build tag, or final tag>
        following: <branch we pick next build tag from>
        sha: <SHA of current build tag>
    """

    tag_avail = {}
    for repo in Component.get_components_of_type("git"):
        tag_avail[repo.git()] = {}
        missing_repos = False
        try:
            execute_git(state, repo.git(), ["rev-parse", state[repo.git()]['version']],
                        capture=True, capture_stderr=True)
            # No exception happened during above call: This is a final release
            # tag.
            tag_avail[repo.git()]['already_released'] = True
            tag_avail[repo.git()]['build_tag'] = state[repo.git()]['version']
        except FileNotFoundError as err:
            print(err)
            missing_repos = True
        except subprocess.CalledProcessError:
            # Exception happened during Git call. This tag doesn't exist, and
            # we must look for and/or create build tags.
            tag_avail[repo.git()]['already_released'] = False

            # Find highest <version>-buildX tag, where X is a number.
            tags = execute_git(state, repo.git(), ["tag"], capture=True)
            highest = -1
            for tag in tags.split('\n'):
                match = re.match("^%s-build([0-9]+)$" % re.escape(state[repo.git()]['version']), tag)
                if match is not None and int(match.group(1)) > highest:
                    highest = int(match.group(1))
                    highest_tag = tag
            if highest >= 0:
                # Assign highest tag so far.
                tag_avail[repo.git()]['build_tag'] = highest_tag
            # Else: Nothing. This repository doesn't have any build tags yet.

        if tag_avail[repo.git()].get('build_tag') is not None:
            sha = execute_git(state, repo.git(), ["rev-parse", "--short",
                                                tag_avail[repo.git()]['build_tag'] + "~0"],
                              capture=True)
            tag_avail[repo.git()]['sha'] = sha

    if missing_repos:
        print("Error: missing repos directories.")
        sys.exit(2)

    return tag_avail

def repo_sort_key(repo):
    """Used in sorted() calls to sort by Git name."""
    return repo.name

def report_release_state(state, tag_avail):
    """Reports the current state of the release, including current build
    tags."""

    print("Mender release: %s" % state['version'])
    fmt_str = "%-27s %-10s %-16s %-20s"
    print(fmt_str % ("REPOSITORY", "VERSION", "PICK NEXT BUILD", "BUILD TAG"))
    print(fmt_str % ("", "", "TAG FROM", ""))
    for repo in sorted(Component.get_components_of_type("git"), key=repo_sort_key):
        if tag_avail[repo.git()]['already_released']:
            tag = state[repo.git()]['version']
            # Report released tags as following themselves, even though behind
            # the scenes we do keep track of a branch we follow. This is because
            # released repositories don't receive build tags.
            following = state[repo.git()]['version']
        else:
            tag = tag_avail[repo.git()].get('build_tag')
            if tag is None:
                tag = "<Needs a new build tag>"
            else:
                tag = "%s (%s)" % (tag, tag_avail[repo.git()]['sha'])
            following = state[repo.git()]['following']

        print(fmt_str % (repo.git(), state[repo.git()]['version'],
                         following, tag))

def annotation_version(repo, tag_avail):
    """Generates the string used in Git tag annotations."""

    match = re.match("^(.*)-build([0-9]+)$", tag_avail[repo.git()]['build_tag'])
    if match is None:
        return "%s version %s." % (repo.git(), tag_avail[repo.git()]['build_tag'])
    else:
        return "%s version %s Build %s." % (repo.git(), match.group(1), match.group(2))

def version_components(version):
    """Returns a four-tuple containing the version componets major, minor, patch
    and beta, as ints. Beta does not include the "b"."""

    match = re.match("^([0-9]+)\.([0-9]+)\.([0-9]+)(?:b([0-9]+))?", version)
    if match is None:
        raise Exception("Invalid version '%s' passed to version_components." % version)

    if match.group(4) is None:
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)), None)
    else:
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4)))

def find_prev_version(tag_list, version):
    """Finds the highest version in tag_list which is less than version.
    tag_list is expected to be sorted with highest version first."""

    (version_major, version_minor, version_patch, version_beta) = version_components(version)

    for tag in tag_list:
        (tag_major, tag_minor, tag_patch, tag_beta) = version_components(tag)

        if tag_major < version_major:
            return tag
        elif tag_major == version_major:
            if tag_minor < version_minor:
                return tag
            elif tag_minor == version_minor:
                if tag_patch < version_patch:
                    return tag
                elif tag_patch == version_patch:
                    if tag_beta is not None and version_beta is None:
                        return tag
                    elif tag_beta is not None and version_beta is not None and tag_beta < version_beta:
                        return tag

    # No lower version found.
    return None

def next_patch_version(prev_version, next_beta=None):
    """Returns the next patch version is a series, based on the given version.
    If next_beta is not None, then the version will be a new beta, instead of a
    new patch release."""

    (major, minor, patch, beta) = version_components(prev_version)
    if next_beta:
        new_version = "%d.%d.%db%d" % (major, minor, patch, next_beta)
    elif beta is not None:
        new_version = "%d.%d.%d" % (major, minor, patch)
    else:
        new_version = "%d.%d.%d" % (major, minor, patch + 1)
    assert prev_version != new_version, "Previous and new version should not be the same!"
    return new_version

def generate_new_tags(state, tag_avail, final):
    """Creates new build tags, and returns the new tags in a modified tag_avail. If
    interrupted anywhere, it makes no change, and returns the original tag_avail
    instead."""

    output = execute_git(state, "integration", ["show", "-s"], capture=True)
    if output.find(VERSION_BUMP_STRING) >= 0:
        # Previous version bump detected. Roll back one commit.
        execute_git(state, "integration", ["reset", "--hard", "HEAD~1"])

    # Find highest of all build tags in all repos.
    highest = 0
    for repo in Component.get_components_of_type("git"):
        if not tag_avail[repo.git()]['already_released'] and tag_avail[repo.git()].get('build_tag') is not None:
            match = re.match(".*-build([0-9]+)$", tag_avail[repo.git()]['build_tag'])
            if match is not None and int(match.group(1)) > highest:
                highest = int(match.group(1))

    # Assign new build tags to each repo based on our previous findings.
    next_tag_avail = copy.deepcopy(tag_avail)
    for repo in Component.get_components_of_type("git"):
        if not tag_avail[repo.git()]['already_released']:
            if final:
                # For final tag, point to the previous build tag, not the
                # version we follow.
                # "~0" is used to avoid a tag pointing to another tag. It should
                # point to the commit.
                sha = execute_git(state, repo.git(), ["rev-parse", "--short",
                                                    tag_avail[repo.git()]['build_tag'] + "~0"],
                                  capture=True)
                # For final tag, use actual version.
                next_tag_avail[repo.git()]['build_tag'] = state[repo.git()]['version']
            else:
                # For build tag, point the next tag to the last version of the
                # branch we follow.
                # "~0" is used to avoid a tag pointing to another tag. It should
                # point to the commit.
                sha = execute_git(state, repo.git(), ["rev-parse", "--short",
                                                    state[repo.git()]['following'] + "~0"],
                                  capture=True)
                # For non-final, use next build number.
                next_tag_avail[repo.git()]['build_tag'] = "%s-build%d" % (state[repo.git()]['version'], highest + 1)

            next_tag_avail[repo.git()]['sha'] = sha

            print_line()
            if tag_avail[repo.git()].get('build_tag') is None:
                # If there is no existing tag, just display latest commit.
                print("The latest commit in %s will be:" % repo.git())
                execute_git(state, repo.git(), ["log", "-n1", sha])
            else:
                # If there is an existing tag, display range.
                print("The new commits in %s will be:" % repo.git())
                execute_git(state, repo.git(), ["log", "%s..%s" % (tag_avail[repo.git()]['build_tag'], sha)])
            print()

    if not final:
        print("Next build is build %d." % (highest + 1))
    print("Each repository's new tag will be:")
    report_release_state(state, next_tag_avail)

    reply = ask("Should each repository be tagged with this new build tag and pushed? ")
    if not reply.startswith("Y") and not reply.startswith("y"):
        return tag_avail

    # Create temporary directory to make changes in.
    tmpdir = setup_temp_git_checkout(state, "integration", state['integration']['following'])
    try:
        prev_version = find_prev_version(sorted_final_version_list(tmpdir),
                                         next_tag_avail['integration']['build_tag'])

        changelogs = []

        # Modify docker tags in docker-compose file.
        for repo in sorted(Component.get_components_of_type("git"), key=repo_sort_key):
            if repo.git() == "integration":
                continue

            set_docker_compose_version_to(tmpdir, repo,
                                          next_tag_avail[repo.git()]['build_tag'])
            if prev_version:
                try:
                    prev_repo_version = version_of(os.path.join(state['repo_dir'], "integration"),
                                                   repo.yml_components()[0], in_integration_version=prev_version)
                except KeyError:
                    # Means that this repo didn't exist in earlier integration
                    # versions.
                    prev_repo_version = None
            else:
                prev_repo_version = None
            if prev_repo_version:
                if prev_repo_version != next_tag_avail[repo.git()]['build_tag']:
                    changelogs.append("Changelog: Upgrade %s to %s."
                                      % (repo.git(), next_tag_avail[repo.git()]['build_tag']))
            else:
                changelogs.append("Changelog: Add %s %s."
                                  % (repo.git(), next_tag_avail[repo.git()]['build_tag']))
        if len(changelogs) == 0:
            changelogs.append("Changelog: None")

        print_line()
        print("Changes to commit:")
        print()
        execute_git(state, tmpdir, ["diff"])
        git_list = []
        git_list.append((state, tmpdir,
                         ["commit", "-a", "-s", "-m",
                          "%s %s.\n\n%s"
                          % (VERSION_BUMP_STRING, next_tag_avail["integration"]['build_tag'],
                             "\n".join(changelogs))]))
        if not query_execute_git_list(git_list):
            return tag_avail

        # Because of the commit above, integration repository now has a new SHA.
        sha = execute_git(state, tmpdir,
                          ["rev-parse", "--short", "HEAD~0"],
                          capture=True)
        next_tag_avail["integration"]['sha'] = sha
        # Fetch the SHA from the tmpdir to make the object available in the
        # original repository.
        execute_git(state, "integration", ["fetch", tmpdir, "HEAD"], capture=True)
    finally:
        cleanup_temp_git_checkout(tmpdir)

    # Prepare Git tag and push commands.
    git_list = []
    for repo in Component.get_components_of_type("git"):
        if not next_tag_avail[repo.git()]['already_released']:
            git_list.append((state, repo.git(), ["tag", "-a", "-m", annotation_version(repo, next_tag_avail),
                                               next_tag_avail[repo.git()]['build_tag'],
                                               next_tag_avail[repo.git()]['sha']]))
            remote = find_upstream_remote(state, repo.git())
            git_list.append((state, repo.git(), ["push", remote, next_tag_avail[repo.git()]['build_tag']]))

    if not query_execute_git_list(git_list):
        return tag_avail

    # If this was the final tag, reflect that in our data.
    for repo in Component.get_components_of_type("git"):
        if not next_tag_avail[repo.git()]['already_released'] and final:
            next_tag_avail[repo.git()]['already_released'] = True

    return next_tag_avail

def get_extra_buildparams_from_jenkins():
    global EXTRA_BUILDPARAMS_CACHE
    if EXTRA_BUILDPARAMS_CACHE is not None:
        return EXTRA_BUILDPARAMS_CACHE

    try:
        import requests
    except ImportError:
        print("requests module missing, try running 'sudo pip3 install requests'.")
        sys.exit(2)

    init_jenkins_creds()
    if not JENKINS_USER or not JENKINS_PASSWORD:
        logging.warn(JENKINS_CREDS_MISSING_ERR)

    # Fetch list of parameters from Jenkins.
    reply = requests.get("%s/%s/api/json" % (JENKINS_SERVER, JENKINS_JOB),
                         auth=(JENKINS_USER, JENKINS_PASSWORD), verify=False)
    jobInfo = json.loads(reply.content.decode())
    parameters = [prop["parameterDefinitions"] for prop in jobInfo["property"] if prop["_class"] == "hudson.model.ParametersDefinitionProperty"]
    assert len(parameters) == 1, "Was expecting one hudson.model.ParametersDefinitionProperty, got %d" % len(parameters)
    parameters = parameters[0]

    def jenkinsParamToDefaultMap(param):
        if param["type"] == "BooleanParameterDefinition":
            type = "bool"
            value = "on" if param["defaultParameterValue"]["value"] else ""
        elif param["type"] == "StringParameterDefinition":
            type = "string"
            if param.get("defaultParameterValue") is None:
                value = ""
            else:
                value = param["defaultParameterValue"]["value"]
        else:
            raise Exception("Parameter has unknown type %s. Don't know how to handle that!" % param["type"])
        return (param["name"], type, value)

    # Add all fetched parameters that are not part of our versioned repositories
    # as extra build parameters.
    extra_buildparams = {}
    in_versioned_repos = {}
    for key in GIT_TO_BUILDPARAM_MAP.keys():
        for repo in Component.get_components_of_type("git"):
            if repo.git() == key:
                in_versioned_repos[GIT_TO_BUILDPARAM_MAP[key]] = True
                # Break out of innermost loop.
                break

    for key, type, value in [jenkinsParamToDefaultMap(param) for param in parameters]:
        # Skip keys that are in versioned repos.
        if not in_versioned_repos.get(key):
            extra_buildparams[key] = JenkinsParam(type, value)

    EXTRA_BUILDPARAMS_CACHE = extra_buildparams
    return extra_buildparams

def trigger_jenkins_build(state, tag_avail):
    try:
        import requests
    except ImportError:
        print("requests module missing, try running 'sudo pip3 install requests'.")
        sys.exit(2)

    init_jenkins_creds()
    if not JENKINS_USER or not JENKINS_PASSWORD:
        raise SystemExit(JENKINS_CREDS_MISSING_ERR)

    extra_buildparams = get_extra_buildparams_from_jenkins()

    for param in extra_buildparams.keys():
        if state_value(state, ["extra_buildparams", param]) is None:
            update_state(state, ["extra_buildparams", param], extra_buildparams[param].value)

    params = None

    # Allow changing of build parameters.
    while True:
        if params is None:
            # We'll be adding parameters here that shouldn't be in 'state', so make a
            # copy.
            params = copy.deepcopy(state['extra_buildparams'])

            # Populate parameters with build tags for each repository.
            postdata = []
            for repo in sorted(Component.get_components_of_type("git"), key=repo_sort_key):
                if tag_avail[repo.git()].get('build_tag') is None:
                    print("%s doesn't have a build tag yet!" % repo.git())
                    return
                params[GIT_TO_BUILDPARAM_MAP[repo.git()]] = tag_avail[repo.git()]['build_tag']

        print_line()
        fmt_str = "%-50s %-20s"
        print(fmt_str % ("Build parameter", "Value"))
        for param in sorted(params.keys()):
            print(fmt_str % (param, params[param]))

        reply = ask("Will trigger a build with these values, ok? (yes) ")
        if reply.startswith("Y") or reply.startswith("y"):
            break

        reply = ask("Do you want to change any of the parameters (Y/N/open in Editor)? ")
        if reply.upper().startswith("E"):
            if os.environ.get("EDITOR"):
                editor = os.environ.get("EDITOR")
            else:
                editor = "vi"
            subprocess.call("%s %s" % (editor, RELEASE_TOOL_STATE), shell=True)
            with open(RELEASE_TOOL_STATE) as fd:
                state.clear()
                state.update(yaml.load(fd))
            # Trigger update of parameters from disk.
            params = None
            continue
        elif not reply.upper().startswith("Y"):
            return

        substr = ask("Which one (substring is ok as long as it's unique)? ")
        found = 0
        for param in params.keys():
            if param.find(substr) >= 0:
                name = param
                found += 1
        if found == 0:
            print("Parameter not found!")
            continue
        elif found > 1:
            print("String not unique!")
            continue
        params[name] = ask("Ok. New value? ")

        if extra_buildparams.get(name) is not None:
            # Extra build parameters, that are not part of the build tags for
            # each repository, should be saved persistently in the state file so
            # that they can be repeated in subsequent builds.
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

        if extra_buildparams.get(param[0]) is not None and extra_buildparams[param[0]].type == "bool":
            if param[1] == "on":
                jdata['parameter'].append({"name": param[0], "value": True})
            elif param[1] == "":
                jdata['parameter'].append({"name": param[0], "value": False})
        else:
            jdata['parameter'].append({"name": param[0], "value": param[1]})

    try:
        postdata.append(("statusCode", "303"))
        jdata["statusCode"] = "303"
        postdata.append(("redirectTo", "."))
        jdata["redirectTo"] = "."
        postdata.append(("json", json.dumps(jdata)))

        reply = requests.post("%s/%s/build?delay=0sec" % (JENKINS_SERVER, JENKINS_JOB),
                              data=postdata, auth=(JENKINS_USER, JENKINS_PASSWORD), verify=False)
        if reply.status_code < 200 or reply.status_code >= 300:
            print("Request returned: %d: %s" % (reply.status_code, reply.reason))
        else:
            print("Build started.")
            # Crude way to find build number, pick first number starting with a
            # hash between two html tags.
            match = re.search('>#([0-9]+)<', reply.content.decode())
            if match is not None:
                print("Link: %s/%s/%s/" % (JENKINS_SERVER, JENKINS_JOB, match.group(1)))
            else:
                print("Unable to determine build number.")
    except Exception:
        print("Failed to start build:")
        traceback.print_exc()

def do_license_generation(state, tag_avail):
    print("Setting up temporary Git workspace...")

    def tag_or_followed_branch(repo_git):
        if tag_avail[repo_git].get('build_tag') is None:
            return state[repo_git]['following']
        else:
            return tag_avail[repo_git]['build_tag']

    tmpdirs = []
    for repo in Component.get_components_of_type("git", only_release=True):
        tmpdirs.append(setup_temp_git_checkout(state, repo.git(), tag_or_followed_branch(repo.git())))
    for repo in Component.get_components_of_type("git", only_non_release=True):
        remote = find_upstream_remote(state, repo.git())
        tmpdirs.append(setup_temp_git_checkout(state, repo.git(), remote + "/master"))

    try:
        with open("generated-license-text.txt", "w") as fd:
            subprocess.check_call([os.path.realpath(os.path.join(os.path.dirname(sys.argv[0]), "license-overview-generator")),
                                   "--called-from-release-tool", "--dir", os.path.dirname(tmpdirs[0])],
                                  stdout=fd)

        print_line()
        print("Will need to fetch the GUI licences from its container. Do you want to:")
        print("1) Build container manually")
        print("   Use this when you have not built anything in Jenkins yet")
        print("2) Fetch container from dockerhub")
        print("   Use this when you have built in Jenkins")
        reply = ask("? ")

        if reply == "1":
            gui_tag = "mendersoftware/gui:tmp"
            for tmpdir in tmpdirs:
                if os.path.basename(tmpdir) == "gui":
                    query_execute_list([["docker", "build", "-t", gui_tag, tmpdir]])
                    break
        elif reply == "2":
            gui_tag = "mendersoftware/gui:%s" % tag_or_followed_branch("gui")
            query_execute_list([["docker", "pull", gui_tag]])
        else:
            return

        executed = query_execute_list([
            ["docker", "run", "-d", "--name", "release_tool_gui_licenses", gui_tag],
            ["docker", "cp", "release_tool_gui_licenses:/var/www/mender-gui/dist/disclaimer.txt", "gui-licenses.txt"],
            ["docker", "rm", "-f", "release_tool_gui_licenses"],
        ])
        if not executed:
            return

    except subprocess.CalledProcessError:
        print()
        print("Command failed with the above error.")
        return
    finally:
        for tmpdir in tmpdirs:
            cleanup_temp_git_checkout(tmpdir)

    with open("generated-license-text.txt", "a") as fd, open("gui-licenses.txt") as gui_licenses:
        fd.write("--------------------------------------------------------------------------------\n")
        fd.write(gui_licenses.read())
    os.remove("gui-licenses.txt")

    print_line()
    print("License overview successfully generated!")
    print("Output is captured in generated-license-text.txt.")

def set_docker_compose_version_to(dir, repo, tag):
    """Modifies docker-compose files in the given directory so that repo_docker
    image points to the given tag."""

    for yml in repo.yml_components():
        compose_files = docker_compose_files_list(dir)
        for filename in compose_files:
            old = open(filename)
            new = open(filename + ".tmp", "w")
            for line in old:
                # Replace build tag with a new one.
                line = re.sub(r"^(\s*image:\s*mendersoftware/%s:)\S+(\s*)$" % re.escape(yml.yml()),
                              r"\g<1>%s\2" % tag, line)
                new.write(line)
            new.close()
            old.close()
            os.rename(filename + ".tmp", filename)

def purge_build_tags(state, tag_avail):
    """Gets rid of all tags in all repositories that match the current version
    of each repository and ends in '-build[0-9]+'. Then deletes this from
    upstream as well."""

    git_list = []
    for repo in Component.get_components_of_type("git"):
        remote = find_upstream_remote(state, repo.git())
        tag_list = execute_git(state, repo.git(), ["tag"], capture=True).split('\n')
        to_purge = []
        for tag in tag_list:
            if re.match('^%s-build[0-9]+$' % re.escape(state[repo.git()]['version']), tag):
                to_purge.append(tag)
        if len(to_purge) > 0:
            git_list.append((state, repo.git(), ["tag", "-d"] + to_purge))
            git_list.append((state, repo.git(), ["push", remote] + [":%s" % tag for tag in to_purge]))

    query_execute_git_list(git_list)

def find_default_following_branch(state, repo, version):
    remote = find_upstream_remote(state, repo.git())
    branch = re.sub(r"\.[^.]+$", ".x", version)
    return "%s/%s" % (remote, branch)

def assign_default_following_branch(state, repo):
    update_state(state, [repo.git(), 'following'],
                 find_default_following_branch(state, repo, state[repo.git()]['version']))

def merge_release_tag(state, tag_avail, repo):
    """Merge tag into version branch, but only for Git history's sake, the 'ours'
    merge strategy keeps the branch as it is, the changes in the tag are not
    pulled in. Without this merge, Git won't auto-grab tags without using "git
    fetch --tags", which is inconvenient for users.
    """

    if not tag_avail[repo.git()]['already_released']:
        print("Repository must have a final release tag before the tag can be merged!")
        return

    # Do the job in a temporary Git repo. Note that we check out the currently
    # followed branch, which may theoretically be later than the released tag.
    # This is because this needs to be pushed to the tip of the branch, not to
    # where the tag is.
    tmpdir = setup_temp_git_checkout(state, repo.git(), state[repo.git()]['following'])
    try:
        # Get a branch name for the currently checked out branch.
        branch = execute_git(state, tmpdir, ["symbolic-ref", "--short", "HEAD"],
                             capture=True)

        # Merge the tag into it.
        git_list = [((state, tmpdir, ["merge", "-s", "ours", "-m",
                                      "Merge tag %s into %s using 'ours' merge strategy."
                                      % (tag_avail[repo.git()]['build_tag'], branch),
                                      tag_avail[repo.git()]['build_tag']]))]
        if not query_execute_git_list(git_list):
            return

        # And then fetch that object back into the original repository, which
        # remains untouched.
        execute_git(state, repo.git(), ["fetch", tmpdir, branch])

        # Push it to upstream.
        upstream = find_upstream_remote(state, repo.git())
        git_list = [((state, repo.git(), ["push", upstream, "FETCH_HEAD:refs/heads/%s"
                                        % branch]))]
        if not query_execute_git_list(git_list):
            return
    finally:
        cleanup_temp_git_checkout(tmpdir)

def push_latest_docker_tags(state, tag_avail):
    """Make all the Docker ":latest" tags point to the current release."""

    for repo in Component.get_components_of_type("git"):
        if not tag_avail[repo.git()]['already_released']:
            print('You cannot push the ":latest" Docker tags without making final release tags first!')
            return

    print("This requires the versioned containers to be built and pushed already.")
    reply = ask("Has the final build finished successfully? ")
    if not reply.startswith("Y") and not reply.startswith("y"):
        return

    # Only for the message. We need to generate a new one for each repository.
    overall_minor_version = state['version'][0:state['version'].rindex('.')]

    for tip in [overall_minor_version, "latest"]:
        reply = ask('Do you want to update ":%s" tags? ' % tip)
        if not reply.startswith("Y") and not reply.startswith("y"):
            continue

        exec_list = []
        for image in Component.get_components_of_type("docker_image"):
            # Even though the version is already in 'tip', this is for the
            # overall Mender version. We need the specific one for the
            # repository.
            repo = image.associated_components_of_type("git")[0]
            if tip == "latest":
                minor_version = "latest"
            else:
                minor_version = state[repo.git()]['version'][0:state[repo.git()]['version'].rindex('.')]

            exec_list.append(["docker", "pull",
                              "mendersoftware/%s:%s" % (image.docker_image(), tag_avail[repo.git()]['build_tag'])])
            exec_list.append(["docker", "tag",
                              "mendersoftware/%s:%s" % (image.docker_image(), tag_avail[repo.git()]['build_tag']),
                              "mendersoftware/%s:%s" % (image.docker_image(), minor_version)])
            exec_list.append(["docker", "push", "mendersoftware/%s:%s" % (image.docker_image(), minor_version)])

        query_execute_list(exec_list)

def create_release_branches(state, tag_avail):
    print("Checking if any repository needs a new branch...")

    any_repo_needs_branch = False

    for repo in Component.get_components_of_type("git"):
        if tag_avail[repo.git()]['already_released']:
            continue

        remote = find_upstream_remote(state, repo.git())

        try:
            execute_git(state, repo.git(), ["rev-parse", state[repo.git()]['following']],
                        capture=True, capture_stderr=True)
        except subprocess.CalledProcessError:
            any_repo_needs_branch = True
            print_line()
            reply = ask(("%s does not have a branch '%s'. Would you like to create it, "
                         + "and base it on latest '%s/master' (if you don't want to base "
                         + "it on '%s/master' you have to do it manually)? ")
                        % (repo.git(), state[repo.git()]['following'], remote, remote))
            if not reply.startswith("Y") and not reply.startswith("y"):
                continue

            cmd_list = []
            cmd_list.append((state, repo.git(), ["push", remote, "%s/master:refs/heads/%s"
                                           # Slight abuse of basename() to get branch basename.
                                           % (remote, os.path.basename(state[repo.git()]['following']))]))
            query_execute_git_list(cmd_list)

    if any_repo_needs_branch:
        reply = ask("Do you want to update all the docker-compose files to new branch values in integration? ")
        if reply.upper().startswith("Y"):
            do_docker_compose_branches_from_follows(state)
    else:
        # Matches the beginning text above.
        print("No.")

def do_beta_to_final_transition(state):
    for repo in Component.get_components_of_type("git"):
        version = state[repo.git()]['version']
        version = re.sub("b[0-9]+$", "", version)
        update_state(state, [repo.git(), 'version'], version)

    version = state['version']
    version = re.sub("b[0-9]+$", "", version)
    update_state(state, ['version'], version)

def do_docker_compose_branches_from_follows(state):
    remote = find_upstream_remote(state, "integration")
    checkout = setup_temp_git_checkout(state, "integration", state['integration']['following'])

    try:
        for repo in sorted(Component.get_components_of_type("git"), key=repo_sort_key):
            branch = state[repo.git()]["following"]
            slash = branch.rfind('/')
            if slash >= 0:
                bare_branch = branch[slash+1:]
            else:
                bare_branch = branch

            set_docker_compose_version_to(checkout, repo, bare_branch)

        print("This is the diff:")
        execute_git(state, checkout, ["diff"])

        bare_branch = re.sub(".*/", "", state['integration']['following'])
        cmd = ["commit", "-asm",
"""Update branch references for %s.

Changelog: None"""
               % bare_branch]
        if not query_execute_git_list([(state, checkout, cmd)]):
            return

        if state['integration']['following'] == bare_branch:
            print(
"""Cannot push the update docker-compose files if integration is not following a
remote branch. Stopping here so that you can push yourself if desired.
The result commit has been put in %s,
which will be removed after you press Enter. Please enter the push command there
if you wish to push the new commit.
"""
                % checkout)
            ask("Press Enter when finished...")
            return

        execute_git(state, "integration", ["fetch", checkout, bare_branch])

        if not query_execute_git_list([(state, "integration", ["push", remote, "FETCH_HEAD:refs/heads/%s" % bare_branch])]):
            return

    finally:
        cleanup_temp_git_checkout(checkout)

    print()
    print("After this it is usually a good idea to re-fetch git repos,")
    print("so will ask about that next.")
    ask("Press Enter...")
    refresh_repos(state)

def do_build(args):
    """Handles building: triggering a build of the given Mender version. Saves
    the used parameters in the home directory so they can be reused in the next
    build."""

    global RELEASE_TOOL_STATE
    RELEASE_TOOL_STATE = os.path.join(os.environ['HOME'], ".release-tool.yml")

    if os.path.exists(RELEASE_TOOL_STATE):
        print("Fetching cached parameters from %s. Delete to reset."
              % RELEASE_TOOL_STATE)
        with open(RELEASE_TOOL_STATE) as fd:
            state = yaml.load(fd)
    else:
        state = {}

    if state_value(state, ['repo_dir']) is None:
        repo_dir = os.path.normpath(os.path.join(integration_dir(), ".."))
        print(("Guessing that your directory of all repositories is %s. "
               + "Edit %s manually to change it.")
              % (repo_dir, RELEASE_TOOL_STATE))
        update_state(state, ["repo_dir"], repo_dir)

    if args.build is True:
        if state_value(state, ['version']) is None:
            print("When there is no earlier cached build, you must give --build a VERSION argument.")
            sys.exit(1)
        tag_avail = check_tag_availability(state)
    else:
        update_state(state, ["version"], args.build)
        for repo in Component.get_components_of_type("git"):
            if repo.git() == "integration":
                update_state(state, [repo.git(), "version"], args.build)
            else:
                version = version_of(integration_dir(), repo.yml_components()[0], args.build)
                update_state(state, [repo.git(), "version"], version)
        tag_avail = check_tag_availability(state)
        for repo in Component.get_components_of_type("git"):
            tag_avail[repo.git()]['build_tag'] = state[repo.git()]["version"]

    extra_buildparams = get_extra_buildparams_from_jenkins()

    for pr in args.pr or []:
        match = re.match("^([^/]+)/([0-9]+)$", pr)
        if match is None:
            raise Exception("%s is not a valid repo/pr pair!" % pr)
        repo = match.group(1)
        assert repo in GIT_TO_BUILDPARAM_MAP.keys(), "%s needs to be in GIT_TO_BUILDPARAM_MAP" % repo
        if GIT_TO_BUILDPARAM_MAP[repo] in extra_buildparams:
            # For non-version repos
            update_state(state, ["extra_buildparams", GIT_TO_BUILDPARAM_MAP[repo]], "pull/%s/head" % match.group(2))
        else:
            # For versioned Mender repos.
            tag_avail[repo]['build_tag'] = "pull/%s/head" % match.group(2)

    trigger_jenkins_build(state, tag_avail)

def determine_version_to_include_in_release(state, repo):
    version = state_value(state, [repo.git(), 'version'])

    if version is not None:
        return version

    # Is there already a version in the same series? Look at integration.
    tag_list = sorted_final_version_list(integration_dir())
    prev_of_integration = find_prev_version(tag_list, state['version'])
    (overall_major, overall_minor, overall_patch, overall_beta) = version_components(state['version'])
    (prev_major, prev_minor, prev_patch, prev_beta) = version_components(prev_of_integration)

    prev_of_repo = None
    new_repo_version = None
    follow_branch = None
    if overall_major == prev_major and overall_minor == prev_minor:
        # Same series. Us it as basis.
        prev_of_repo = version_of(integration_dir(), repo.yml_components()[0], in_integration_version=prev_of_integration)
        new_repo_version = next_patch_version(prev_of_repo, next_beta=overall_beta)
        follow_branch = find_default_following_branch(state, repo, new_repo_version)
    else:
        # No series exists. Base on master.
        version_list = sorted_final_version_list(os.path.join(state['repo_dir'], repo.git()))
        if len(version_list) > 0:
            prev_of_repo = version_list[0]
            (major, minor, patch, beta) = version_components(prev_of_repo)
            new_repo_version = "%d.%d.0" % (major, minor + 1)
        else:
            # No previous version at all. Start at 1.0.0.
            prev_of_repo = None
            new_repo_version = "1.0.0"
        if overall_beta:
            new_repo_version += "b%d" % overall_beta
        follow_branch = "%s/master" % find_upstream_remote(state, repo.git())

    if prev_of_repo:
        cmd = ["log", "%s..%s" % (prev_of_repo, follow_branch)]

        print("cd %s && git %s:" % (repo.git(), " ".join(cmd)))
        execute_git(state, repo.git(), cmd)

        print()
        print("Above is the output of 'cd %s && git %s'" % (repo.git(), " ".join(cmd)))
        reply = ask("Based on this, is there a reason for a new release of %s? "
                    % repo.git())

    if not prev_of_repo or reply.lower().startswith("y"):
        reply = ask("Should the new release of %s be version %s? "
                    % (repo.git(), new_repo_version))
        if reply.lower().startswith("y"):
            update_state(state, [repo.git(), 'version'], new_repo_version)
    else:
        reply = ask("Should the release of %s be left at the previous version %s? "
                    % (repo.git(), prev_of_repo))
        if reply.lower().startswith("y"):
            update_state(state, [repo.git(), 'version'], prev_of_repo)

    if state_value(state, [repo.git(), 'version']) is None:
        reply = ask("Ok. Please input the new version of %s manually: " % repo.git())
        update_state(state, [repo.git(), 'version'], reply)

    print()
    print_line()

def do_release():
    """Handles the interactive menu for doing a release."""

    global RELEASE_TOOL_STATE
    RELEASE_TOOL_STATE = "release-state.yml"

    if os.path.exists(RELEASE_TOOL_STATE):
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

    # Fill the state data.
    if new_release:
        state = {}
    else:
        print("Loading existing release state data...")
        print("Note that you can always edit or delete %s manually" % RELEASE_TOOL_STATE)
        fd = open(RELEASE_TOOL_STATE)
        state = yaml.load(fd)
        fd.close()

    if state_value(state, ['repo_dir']) is None:
        reply = ask("Which directory contains all the Git repositories? ")
        reply = re.sub("~", os.environ['HOME'], reply)
        update_state(state, ['repo_dir'], reply)

    if state_value(state, ['version']) is None:
        update_state(state, ['version'], ask("Which release of Mender will this be? "))

    update_state(state, ["integration", 'version'], state['version'])

    input = ask("Do you want to fetch all the latest tags and branches in all repositories (will not change checked-out branch)? ")
    if input.startswith("Y") or input.startswith("y"):
        refresh_repos(state)

    for repo in sorted(Component.get_components_of_type("git"), key=repo_sort_key):
        determine_version_to_include_in_release(state, repo)

    # Fill data about available tags.
    tag_avail = check_tag_availability(state)

    for repo in Component.get_components_of_type("git"):
        if state_value(state, [repo.git(), "following"]) is None:
            # Follow "1.0.x" style branches by default.
            assign_default_following_branch(state, repo)

    create_release_branches(state, tag_avail)

    first_time = True
    while True:
        if first_time:
            first_time = False
        else:
            # Provide a break to see output from what was just done.
            ask("Press Enter... ")

        print_line()
        print("Current state of release:")
        report_release_state(state, tag_avail)

        minor_version = state['version'][0:state['version'].rindex('.')]

        print("What do you want to do?")
        print("-- Main operations")
        if re.search("b[0-9]+$", state['version']) and tag_avail['integration']['already_released']:
            print("  O) Move from beta build tags to final build tags")
        print("  R) Refresh all repositories from upstream (git fetch)")
        print("  T) Generate and push new build tags")
        print("  B) Trigger new Jenkins build using current tags")
        print("  L) Generate license text for all dependencies")
        print("  F) Tag and push final tag, based on current build tag")
        print('  D) Update ":%s" and/or ":latest" Docker tags to current release' % minor_version)
        print("  Q) Quit (your state is saved in %s)" % RELEASE_TOOL_STATE)
        print()
        print("-- Less common operations")
        print("  P) Push current build tags (not necessary unless -s was used before)")
        print("  U) Purge build tags from all repositories")
        print('  M) Merge "integration" release tag into release branch')
        print("  C) Create new series branch (A.B.x style) for each repository that lacks one")
        print("  I) Put currently followed branch names into integration's docker-compose ")
        print("     files. Use this to update the integration repository to new branch names")
        print("     after you've branched it.")

        reply = ask("Choice? ")

        if reply.lower() == "q":
            break
        if reply.lower() == "r":
            refresh_repos(state)
            # Refill data about available tags, since it may have changed.
            tag_avail = check_tag_availability(state)
        elif reply.lower() == "t":
            tag_avail = generate_new_tags(state, tag_avail, final=False)
        elif reply.lower() == "f":
            tag_avail = generate_new_tags(state, tag_avail, final=True)
            print()
            reply = ask("Purge all build tags from all repositories (recommended)? ")
            if reply.lower() == "y":
                purge_build_tags(state, tag_avail)
            reply = ask('Merge "integration" release tag into version branch (recommended)? ')
            if reply.lower() == "y":
                merge_release_tag(state, tag_avail, Component.get_component_of_type("git", "integration"))
        elif reply.lower() == "d":
            push_latest_docker_tags(state, tag_avail)
        elif reply.lower() == "p":
            git_list = []
            for repo in Component.get_components_of_type("git"):
                remote = find_upstream_remote(state, repo.git())
                git_list.append((state, repo.git(), ["push", remote, tag_avail[repo.git()]['build_tag']]))
            query_execute_git_list(git_list)
        elif reply.lower() == "b":
            trigger_jenkins_build(state, tag_avail)
        elif reply.lower() == "l":
            do_license_generation(state, tag_avail)
        elif reply.lower() == "u":
            purge_build_tags(state, tag_avail)
        elif reply.lower() == "m":
            merge_release_tag(state, tag_avail, Component.get_component_of_type("git", "integration"))
        elif reply.lower() == "c":
            create_release_branches(state, tag_avail)
        elif reply.lower() == "o":
            do_beta_to_final_transition(state)
            tag_avail = check_tag_availability(state)
        elif reply.lower() == "i":
            do_docker_compose_branches_from_follows(state)
        else:
            print("Invalid choice!")

def do_set_version_to(args):
    """Handles --set-version-of argument."""

    if args.version is None:
        print("--set-version-of requires --version")
        sys.exit(1)

    repo = Component.get_component_of_any_type(args.set_version_of)
    set_docker_compose_version_to(integration_dir(), repo, args.version)

def do_integration_versions_including(args):
    if not args.version:
        print("--integration-versions-including requires --version argument")
        sys.exit(2)

    git_dir = integration_dir()
    remote = find_upstream_remote(None, git_dir)
    output = execute_git(None, git_dir, ["for-each-ref", "--format=%(refname:short)",
                                         "--sort=-version:refname",
                                         "refs/tags/*",
                                         "refs/remotes/%s/master" % remote,
                                         "refs/remotes/%s/[1-9]*" % remote],
                         capture=True)
    candidates = []
    for line in output.strip().split('\n'):
        # Filter out build tags.
        if re.search("-build", line):
            continue

        candidates.append(line)

    # Now look at each docker compose file in each branch, and figure out which
    # ones contain the version of the service we are querying.
    matches = []
    for candidate in candidates:
        data = get_docker_compose_data_for_rev(git_dir, candidate)
        try:
            repo = Component.get_component_of_any_type(args.integration_versions_including)
        except KeyError:
            print("Unrecognized repository: %s" % args.integration_versions_including)
            sys.exit(1)
        try:
            version = data[repo.yml_components()[0].yml()]['version']
        except KeyError:
            # If key doesn't exist it's because the version is from before
            # that component existed. So definitely not a match.
            continue
        if version == args.version:
            matches.append(candidate)

    for match in matches:
        print(match)

def figure_out_checked_out_revision(state, repo_git):
    """Finds out what is currently checked out, and returns a list of pairs. The
    first element is the name of what is checked out, the second is either
    "branch" or "tag", referring to what is currently checked out. If neither a
    tag nor branch is checked out, returns None."""

    try:
        ref = execute_git(None, repo_git, ["symbolic-ref", "--short", "HEAD"], capture=True, capture_stderr=True)
        # If the above didn't produce an exception, then we are on a branch.
        return [(ref, "branch")]
    except subprocess.CalledProcessError:
        # Not a branch, fall through to below.
        pass

    # We are not on a branch. Or maybe we are on a branch, but Jenkins
    # checked out the SHA anyway.
    ref = os.environ.get(GIT_TO_BUILDPARAM_MAP[os.path.basename(repo_git)])

    if ref is not None:
        try:
            # Make sure it matches the checked out SHA.
            checked_out_sha = execute_git(None, repo_git, ["rev-parse", "HEAD"], capture=True)
            remote = find_upstream_remote(None, repo_git)
            ref_sha = execute_git(None, repo_git, ["rev-parse", "%s/%s" % (remote, ref)],
                                  capture=True, capture_stderr=True)
            if ref_sha != checked_out_sha:
                # Why isn't the branch mentioned in the build parameters checked
                # out? This should not happen.
                raise Exception(("%s: SHA %s from %s does not match checked out SHA %s. "
                                 + "Although rare, this sometimes happens if a repository is "
                                 + "updated in the very same instant it is pulled. Just restarting "
                                 + "the build should get rid of the problem in most cases.")
                                % (repo_git, ref_sha, ref, checked_out_sha))

            return [(ref, "branch")]
        except subprocess.CalledProcessError:
            # Not a branch. Then fall through to part below.
            pass

    # Not a branch checked out as a SHA either. Try tag then.
    refs = execute_git(None, repo_git, ["tag", "--points-at", "HEAD"], capture=True).split()
    if len(refs) == 0:
        # We are not on a tag either.
        return None

    return [(ref, "tag") for ref in refs]

def do_verify_integration_references(args, optional_too):
    int_dir = integration_dir()
    data = get_docker_compose_data(int_dir)
    problem = False

    repos = Component.get_components_of_type("git", only_release=(not optional_too))

    for repo in repos:
        # integration is not checked, since the current checkout records the
        # version of that one.
        if repo.git() == "integration":
            continue

        # Try some common locations.
        tried = []
        for partial_path in ["..", "../go/src/github.com/mendersoftware"]:
            path = os.path.normpath(os.path.join(int_dir, partial_path, repo.git()))
            tried.append(path)
            if os.path.isdir(path):
                break
        else:
            print("%s not found. Tried: %s"
                  % (repo.git(), ", ".join(tried)))
            sys.exit(2)

        revs = figure_out_checked_out_revision(None, path)
        if revs is None:
            # Unrecognized checkout. Skip the check then.
            continue

        if all([reftype == "branch" and not re.match(r"^([1-9][0-9]*\.[0-9]+\.([0-9]+|x)|master)$", ref) for ref, reftype in revs]):
            # Skip the check if the branch doesn't have a well known name,
            # either a version (with or without beta and build appendix) or
            # "master". If it does not have a well known name, then most likely
            # this is a pull request, and we don't require those to be recorded
            # in the YAML files.
            continue

        for yml in repo.yml_components():
            version = data[yml.yml()]['version']

            if version not in [ref for ref, reftype in revs]:
                if len(revs) > 1:
                    checked_out = "(one of '%s')" % "', '".join([ref for ref, reftype in revs])
                else:
                    checked_out = "'%s'" % revs[0][0]
                print("%s: Checked out Git ref %s does not match tag/branch recorded in integration/*.yml: '%s' (from image tag: '%s')"
                      % (repo.git(), checked_out, version, yml.yml()))
                problem = True

    if problem:
        print("\nMake sure all *.yml files contain the correct versions.")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-g", "--version-of", dest="version_of", metavar="SERVICE",
                        help="Get version of given service")
    parser.add_argument("-i", "--in-integration-version", dest="in_integration_version", metavar="VERSION",
                        help="Used together with the above argument to query for a version of a "
                        + "service which is in the given version of integration, instead of the "
                        + "currently checked out version of integration. If a range is given here "
                        + "it will return the range of the corresponding service.")
    parser.add_argument("-s", "--set-version-of", dest="set_version_of", metavar="SERVICE",
                        help="Write version of given service into docker-compose.yml")
    parser.add_argument("-f", "--integration-versions-including", dest="integration_versions_including", metavar="SERVICE",
                        help="Find version(s) of integration repository that contain the given version of SERVICE, "
                        + " where version is given with --version. Returned as a newline separated list")
    parser.add_argument("-v", "--version", dest="version",
                        help="Version which is used in above two arguments")
    parser.add_argument("-b", "--build", dest="build", metavar="VERSION",
                        const=True, nargs="?",
                        help="Build the given version of Mender")
    parser.add_argument("--pr", dest="pr", metavar="REPO/PR-NUMBER", action="append",
                        help="Can only be used with -b. Specifies a repository and pull request number "
                        + "that should be triggered with the rest of the repository versions. "
                        + "May be specified more than once.")
    parser.add_argument("-l", "--list", metavar="container|docker|git", dest="list", const="git", nargs="?",
                        help="List the Mender repositories in use for this release. The optional "
                        + "argument determines which type of name is returned. The default is git. "
                        + "By default does not list optional repositories.")
    parser.add_argument("-a", "--all", action="store_true", default=False,
                        help="When used with -l, list all repositories, including optional ones.")
    parser.add_argument("--release", action="store_true",
                        help="Start the release process (interactive)")
    parser.add_argument("--simulate-push", action="store_true",
                        help="Simulate (don't do) pushes")
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help="Don't take any action at all")
    parser.add_argument("--verify-integration-references", action="store_true",
                        help="Checks that references in the yaml files match the tags that "
                        + "are checked out in Git. This is intended to catch cases where "
                        + "references to images or tools are out of date. It requires checked-out "
                        + "repositories to exist next to the integration repository, and is "
                        + "usually used only in builds. For branch names (not tags), only "
                        + 'well known names are checked: version numbers and "master" (to avoid '
                        + "pull requests triggering a failure). Respects -a argument.")
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
    elif args.list is not None:
        do_list_repos(args, optional_too=args.all)
    elif args.set_version_of is not None:
        do_set_version_to(args)
    elif args.integration_versions_including is not None:
        do_integration_versions_including(args)
    elif args.build:
        do_build(args)
    elif args.release:
        do_release()
    elif args.verify_integration_references:
        do_verify_integration_references(args, optional_too=args.all)
    else:
        parser.print_help()
        sys.exit(1)

main()
