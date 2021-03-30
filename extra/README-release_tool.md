# release_tool.py

This tool is for internal consumption only, and should not be used outside of
Mender development.

The `release_tool.py` script has four main modes of operation:

* Querying the version of a component in the docker-compose environment.

* Setting the version of a component in the docker-compose environment.

* Tagging, building, and releasing Mender stable releases

* Tagging Hosted Mender releases


## Querying docker-compose versions

To query for a version, use the `--version-of` option, and then specify the name
of a component to check. The name can be given as either Git repository name,
Docker image name, or Docker container name.

For example:

```
$ ./release_tool.py --version-of mender-client
1.0.1
$
```


## Setting docker-compose versions

Setting a docker-compose component version means that either
`docker-compose.yml` or one of its companion files will be changed. This can be
used to change and thereby launch, a different version of a Docker component
than is programmed in the file when checked out from the repository.

To do this, use the `--set-version-of` and `--version` options together. For
example:

```
$ ./release_tool.py --set-version-of mender-client --version 1.2.0
$ git diff
diff --git a/docker-compose.client.yml b/docker-compose.client.yml
index 717848a..a80d963 100644
--- a/docker-compose.client.yml
+++ b/docker-compose.client.yml
@@ -5,6 +5,6 @@ services:
     # mender-client
     #
     mender-client:
-        image: mendersoftware/mender-client-qemu:master
+        image: mendersoftware/mender-client-qemu:1.2.0
         networks:
             - mender
$
```


## Building

The `--build` argument can be used to build a version of Mender, including
correct versions of all the micro services, without having to specify all of
them. Before the build starts, you'll also be given the chance to alter build
parameters.


## Releasing

Releasing is an interactive part of the tool. Below is a tutorial to get into
the workflow, and afterwards a more comprehensive reference to understand some
of the advanced options.

### Tutorial: Release workflow

In this tutorial we go through the typical work flow when doing a release.

#### Preparing for a release

1. The first thing you need to do is to verify that the script has knowledge of
   all the repositories it needs to for a given release. Check `COMPONENT_MAPS`
   variable inside the script, and add or remove repositories as needed. Make
   sure you read the comments above it, since some changes may require
   additional sections to be changed.

2. Before you can use the release mode of the tool, one prerequisite is
   required: All repositories mentioned in `COMPONENT_MAPS` variable inside the
   script source must be available inside a single directory (having them as
   symlinks pointing somewhere else is ok). The script will ask about the
   location of this directory before starting.


#### Launching the script

Launching the script is simply a matter of calling it with `--release`, and not
other arguments:

```
$ ./release_tool.py --release
```

When first launched you will get a series of questions about which version this
should be, and which versions of the components you want to include in it. If
you have run the script before you may instead get a question if you want to
continue the old one or start a new release.

After these questions you will be in the main menu where the release work is
carried out.


#### The release flow

1. The first thing you will want to do is to create some build tags. For this,
   type 'T' into the menu. What this will do is to generate new build tags in
   all the repositories that need them, and push these.

2. Next, you will want to build using these tags in GitLab. For that type 'B'
   into the menu. This will give you a series of build parameters that you can
   check for validity. If you answer no, you'll get the chance to change them,
   otherwise proceed by saying yes.

3. Use the link given to you, and wait for build to finish.

4. Test the build.

5. If issues were found, at this point you will typically revert back to point 1
   and redo the steps from there.

6. However, if the build seems good, it is time to release! To do this, type 'F'
   into the menu. This will create final tags, pointing them to the same commits
   as the last build tag, and then push these. You'll also get some questions
   about various cleanup actions, and the recommendation is to answer yes to all
   of these (see the reference below for more details on exactly what they do).

7. Type 'B' to trigger another build. It's recommended to check the build logs
   to make sure all Docker containers have been pushed successfully.

8. When that build has finished, you'll typically want to update the Docker
   tags, which you can do by typing 'D'. This is not always what you want
   though, see the section about [updating Docker tags to current
   release](#update-docker-tags-to-current-release) below for more details about
   what this does.

9. Congrats, you're done!

Note that at any point you can choose to quit the tool and continue later (a
typical thing to do when leaving for the day or waiting for a build). The script
will save your state and pick up the progress, assuming you choose to continue
the existing release when the tool starts.


### Reference: Main operations


#### Move from beta build tags to final build tags

This moves all version tags from version with beta, so versions without beta, in
order to start building the final. This operation is not displayed if the
current build tag is not a beta version.


#### Refresh all repositories

This simply does a `git fetch --tags` in all repositories to update all remote
branches and tags.


#### Generate and push new build tags

This is normally the first thing one will do when preparing a release. It will
take the version of each component which are scheduled for a new release and
generate new tags of the form `X.Y.Z-buildN`, where `X.Y.Z` is the version of
the component, and `N` is the lowest build number not already existing in any of
the repositories. Afterwards it will push these tags to each repository.

Only repositories that are scheduled for a new release will be tagged;
repositories based on existing versions will be left alone and their release tag
will be used instead of a build tag.

The `integration` repository is special in the tag handling: In addition to
receiving a tag, the tool will make an automatic commit which includes the
altered versions of all the components in `docker-compose.yml` and related
files. Then it will tag the using this new commit. See the section about
[tagging and pushing the final build](#tag-and-push-final-build) for an
illustration about what this means for the Git history.


#### Trigger new GitLab build

This will trigger a new GitLab build using the current build tags.

In addition to the revisions to build, there are additional default parameters
passed to GitLab. These can be changed by answering no when asked to submit the
build and changing the parameters of the user's choice. Parameters that don't
describe component versions will be saved and used in subsequent builds.

Currently you cannot add new parameters via the interface, but these can be
added manually by editing `release-state.yml`.

After the build has been triggered a link is given which points to the build.


#### Tag and push final build

This will tag each repository with the final version tag and push this. Note
that unlike tagging of new build tags, this will not grab the latest version of
the branch, but will tag exactly the commit where the last build tag was. This
is to ensure that you don't accidentally tag the wrong commit after running `git
fetch`.

Afterwards it will ask you whether you want to purge all the build tags for the
release from the repositories, which is recommended, since they have no further
use after the release is out, and they clutter the tag list with many useless
tags.

After the tag purging it will also ask you if you want to merge the current tag
into the release branch of the integration repository. The question you're
probably asking is: Why is this necessary, and why isn't the tag somewhere on
the branch already? The reason is that, in the integration repository, since the
`docker-compose.yml` file and related files have to be edited to insert the
right version there, there will be an extra "leaf commit" which is off the main
release branch, containing only this change. See this illustration:

```
future 1.0.x -->  o
                  .
                  . o  <-- 1.0.1
                  ./
       1.0.x -->  o
                  |
                  o
                  |
                  .
                  .
```

So in other words, 1.0.1 is not on the 1.0.x branch. While this isn't a problem
in itself, it's inconvenient for users for this reason: Git doesn't
automatically pull tags that aren't on any of the branches it pulls. So users
are not going to get the release tags unless they ask for them specifically,
either by using the `--tags` option, or asking for the specific tag.

What we want is this:

```
       1.0.x -->  o
                  |\
                  | o  <-- 1.0.1
                  |/
                  o
                  |
                  o
                  |
                  .
                  .
```

So that the tag is on the branch. This is what happens when merging the release
tag into the release branch. The tool uses a special argument, `git merge -s
ours`, which prevents the actual *changes* from that branch being included, only
the history of the tag is included.


#### Update Docker tags to current release

This updates ":1.x" and ":latest" style Docker tags to the current release, so
that for example "1.0" will point to "1.0.2". You'll be asked about both tag
types, so you don't have to update both (if you already have a "1.1" tag in
addition to "1.0", you probably don't want to update "latest" to "1.0.2".


### Reference: Less common operations


#### Push current build tags

This pushes the current build tags to all Git repositories. This is done
automatically when using the other menu entries, so this is normally not
necessary unless you passed `-s` to the tool earlier, preventing it from
pushing.


#### Purge build tags from all repositories

This has the same effect as the tag purging done after a release, and is only
necessary if you answered no to that question after tagging the final build.


#### Merge "integration" release tag into release branch

This has the same effect as answering yes to the same question when tagging the
final release, and is not necessary unless you answered no there. See that
section for more details.


#### Switch fetching branch

Normally, the tool fetches all commits from upstream branches, and uses the
latest commit from the upstream branch when generating a new tag. This is what
you normally want, since most people don't keep every single one of their local
Git branches up to date, for every repository.

However, there may be cases where this is not appropriate, and you want complete
control over what is being built. In this case you can switch the fetching
branch to the local branches, and the new tags will be generated from these
branches instead. *Be careful* though, if you do this you have to make sure that
all your local branches are up to date, otherwise some tags may be generated
using old branch heads.

Tip: You can also switch only one repository to a local branch, or to a
differently named branch, but then you need to edit the `release-state.yml` file
manually and change the `following` branch of the repository you want.

#### Create new series branch

For each repository that follows a remote branch you will get the option of
pushing a new branch if it lacks a branch of this name. The intended usage of
this command is to create a new 1.1.x branch off of master when 1.1.0 is to be
released. This command is automatically invoked when the script starts, but one
can say no if it's not desired.

#### Put followed branch names into docker-compose

This action updates the docker-compose YAML files to point to the branch names
that the current release is following. The typical use of this action is after
having branched integration, and started the release process using the
`release_tool.py` script, you run this to record the all the new branch
references in the new version.

For example, if you just branched integration version 1.2.x, this still has YAML
files that point to master. By using this action, you can update all of them to
point to the respective 1.x.x branches.


## Verifying integration references

This section describes the `--verify-integration-references` option. What it
does is to check that for each version recorded in one of the YAML files in the
list below, the currently checked out version is the same. The motivation for
providing this check is to make sure releases are always listing the version we
build, so that:

* there is no confusion among users as to which versions belong together.

* we can safely query the versions recorded in the YAML files to provide branch
  names for upload, for example.

Tags are always checked, but branches are only checked if they match well known
patterns, such as a version number or the string "master". This is to avoid
temporary branch names, such as pull requests, triggering a failure, since we
don't expect such branch names to be recorded in the YAML files.

List of YAML files that are checked:

* `docker-compose*.yml`
* `other-components.yml` (non-Docker components)

## Tagging for Hosted Mender

For the hosted Mender release workflow, the `release_tool.py` script is only
used for tagging the final versions. The build and test is carried out outside
of the tool.

Once the software versions deployed in staging have passed all our QA and is
ready to be deployed into production, `release_tool.py` can be used to generate
the production tags.

This process can only be done from `staging` version in integration repo.

Running the command:

```
$ ./release_tool --hosted-release
```

The tool will generate tags of the form `saas-vYYYY.MM.DD` for all backend
repositories from their respective `staging` branches.

Alternatively, a custom version can be specified with:

```
$ ./release_tool --hosted-release --version my-custom-version
```
