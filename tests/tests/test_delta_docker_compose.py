# Copyright 2026 Northern.tech AS
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""Integration tests for the delta-docker-compose Update Module.

The delta module (mender-delta-container-modules) reuses almost all of the base
``docker-compose`` module (docker-compose_base.sh): install/commit/rollback/
cleanup and the compose start/stop/healthcheck logic are inherited verbatim.
Those behaviors are already exercised by test_docker_compose.py and are NOT
re-tested here.

What is delta-specific -- and therefore what this module covers -- is:

  * ``extract_images_from_artifact``: reconstructing the target container images
    on the device from a delta artifact, both in the "pruned shared layers"
    variant (no xdelta3 vcdiffs) and the ``--layer-deltas`` variant (xdelta3
    binary deltas resolved against the locally-present source image).
  * The extra ``xdelta3`` requirement and its failure/rollback paths.
  * That the delta artifact is meaningfully smaller than the full target.

Setup notes / assumptions:

  * The *source* full composition is deployed through the open base
    ``docker-compose`` Update Module (ships in the extended image, same
    assumption as test_docker_compose.py). The *delta* is deployed through the
    proprietary ``delta-docker-compose`` module, which is baked into the
    commercial extended image (mender-client-qemu-extended-commercial) the tests
    boot.
  * Because the base and delta modules use *separate* persistent stores
    (/data/mender-docker-compose vs /data/mender-delta-docker-compose), the delta
    module does not stop the base composition itself -- container replacement
    relies on both compositions using the same compose project name and service
    name, so ``docker compose up`` reconciles them. This mirrors real usage where
    a full artifact is deployed once and subsequent updates are deltas.
  * Host-side generators come from two *independent* sources, so the suite can pin
    mender-container-modules and mender-delta-container-modules separately (the base
    artifact generator is distributed separately from the delta one):
      - gen_docker-compose: the public mender-container-modules, cloned in-fixture
        and pinned by MENDER_CONTAINER_MODULES_VERSION (as test_docker_compose.py);
      - gen_delta-docker-compose: the *private* mender-delta-container-modules,
        provided as a checkout via MENDER_DELTA_CONTAINER_MODULES_PATH (dev-provided
        locally; cloned with a token by CI) -- the tests do not clone it.
    Layer-delta encoding uses a system xdelta3 on PATH (see MEN-10122 re: secondary
    compressor compatibility with the device's xdelta3).
"""

import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile
import uuid

import pytest

from ..common_setup import standard_setup_extended_commercial
from .common_update import common_update_procedure
from ..MenderAPI import DeviceAuthV2, Deployments
from .mendertesting import MenderTesting

DEVICE_TYPE = "qemux86-64"
PROJECT_NAME = "test"
SERVICE_NAME = "srv"
BLOB_SIZE = 8 * 1024 * 1024  # 8 MiB, random so gzip cannot hide the delta savings

FAILING_HEALTHCHECK = """    healthcheck:
      test: ["CMD", "false"]
      interval: 1s
      timeout: 1s
      retries: 1
"""


# ---------------------------------------------------------------------------
# Distribution fixtures (host-side tooling)
# ---------------------------------------------------------------------------


def _delta_repo_path():
    """Path to a checkout of the *private* mender-delta-container-modules (with
    submodules). Provided via MENDER_DELTA_CONTAINER_MODULES_PATH -- dev-provided
    locally, or cloned with a token by a CI before_script; the tests do not clone
    it themselves."""
    path = os.path.abspath(
        os.environ.get(
            "MENDER_DELTA_CONTAINER_MODULES_PATH", "mender-delta-container-modules"
        )
    )
    assert os.path.isdir(path), (
        f"mender-delta-container-modules checkout not found at {path}. "
        "It is a private repo, so the tests do not clone it: set "
        "MENDER_DELTA_CONTAINER_MODULES_PATH to a local checkout "
        "(in CI, a before_script clones it with a token)."
    )
    return path


@pytest.fixture(scope="session")
def base_gen_script():
    """gen_docker-compose -- builds the source/target full compositions the delta
    is generated between.

    From its own mender-container-modules checkout (public repo), cloned in-fixture
    and pinned by MENDER_CONTAINER_MODULES_VERSION -- deliberately *independent* of
    the delta repo, since the base artifact generator is distributed separately, so
    the suite can test a given container-modules version against a given
    delta-container-modules version (mirrors test_docker_compose.py)."""
    with tempfile.TemporaryDirectory() as temp_dir:
        version = os.environ.get("MENDER_CONTAINER_MODULES_VERSION", "main")
        repo_url = "https://github.com/mendersoftware/mender-container-modules.git"

        subprocess.check_call(["git", "clone", repo_url, "."], cwd=temp_dir)
        ref_path = "refs/" + version if version.startswith("pull/") else version
        subprocess.check_call(["git", "fetch", "origin", ref_path], cwd=temp_dir)
        subprocess.check_call(["git", "checkout", "FETCH_HEAD"], cwd=temp_dir)
        subprocess.check_call(["make"], cwd=temp_dir)

        yield os.path.join(temp_dir, "src/gen_docker-compose")


@pytest.fixture(scope="session")
def delta_gen_script():
    """gen_delta-docker-compose -- generates the delta between two compositions."""

    gen_delta = os.path.join(_delta_repo_path(), "src/gen_delta-docker-compose")
    assert os.path.exists(gen_delta), f"gen_delta-docker-compose missing at {gen_delta}"
    return gen_delta


@pytest.fixture(scope="function")
def delta_device(standard_setup_extended_commercial):
    """Device running the commercial extended image, which ships the
    delta-docker-compose Update Module and xdelta3 baked in."""
    return standard_setup_extended_commercial


# ---------------------------------------------------------------------------
# Host-side image / artifact helpers
# ---------------------------------------------------------------------------


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_blob(path, size):
    """Write `size` random bytes and return their sha256."""
    with open(path, "wb") as f:
        f.write(os.urandom(size))
    return _sha256_file(path)


def _running_container_id(device, image_tag):
    """Container id of the running container created from image_tag."""
    cid = device.run(f"docker ps -q --filter ancestor={image_tag}").strip()
    assert cid, f"no running container from image {image_tag}"
    return cid.splitlines()[0]


def _container_file_sha256(device, cid, path):
    """sha256 of a file inside the running container (busybox sha256sum)."""
    return device.run(f"docker exec {cid} sha256sum {path}").split()[0]


def _assert_running(device, present=(), absent=()):
    """Assert image tags are (present) / are not (absent) among running containers."""
    ps = device.run("docker ps")
    for tag in present:
        assert tag in ps, f"expected image {tag} to be running; docker ps:\n{ps}"
    for tag in absent:
        assert tag not in ps, f"image {tag} should not be running; docker ps:\n{ps}"


def _assert_deployment_log_contains(deploy, device_id, deployment_id, needle):
    """Assert the device's deployment log contains `needle`, dumping the full log in
    the failure message so an unexpected failure reason is visible in the report."""
    logs = deploy.get_logs(device_id, deployment_id)
    assert (
        needle in logs
    ), f"expected {needle!r} in the deployment log; full log:\n{logs}"


def _build_and_save(tag, dockerfile, context_dir, out_tar):
    dockerfile_path = os.path.join(context_dir, "Dockerfile")
    with open(dockerfile_path, "w") as f:
        f.write(dockerfile)
    subprocess.check_call(
        ["docker", "build", "-t", tag, "-f", dockerfile_path, context_dir]
    )
    subprocess.check_call(["docker", "save", "-o", out_tar, tag])


def _write_compose(manifests_dir, image_tag, extra=""):
    with open(os.path.join(manifests_dir, "docker-compose.yml"), "w") as f:
        f.write("services:\n")
        f.write(f"  {SERVICE_NAME}:\n")
        f.write(f"    image: {image_tag}\n")
        f.write("    network_mode: bridge\n")
        f.write(extra)


def _make_composition_dir(root, image_tar_src, image_tag, extra=""):
    """Create a manifests/ + images/ pair for a single-service composition."""
    comp = tempfile.mkdtemp(dir=root)
    manifests_dir = os.path.join(comp, "manifests")
    images_dir = os.path.join(comp, "images")
    os.makedirs(manifests_dir)
    os.makedirs(images_dir)
    shutil.copy(
        image_tar_src, os.path.join(images_dir, os.path.basename(image_tar_src))
    )
    _write_compose(manifests_dir, image_tag, extra)
    return manifests_dir, images_dir


_BUSYBOX_BLOB = 'FROM busybox:latest\nCOPY blob /blob\nCMD ["sleep", "infinity"]\n'


def _image_composition(work, tag, dockerfile, context_dir, compose_extra=""):
    """Build+save image `tag` and make a single-service composition dir for it.
    Returns (manifests_dir, images_dir, image_tar)."""
    tar = os.path.join(work, tag + ".tar")
    _build_and_save(tag, dockerfile, context_dir, tar)
    manifests, images = _make_composition_dir(work, tar, tag, extra=compose_extra)
    return manifests, images, tar


def _build_source_and_derived(work, src_tag, derived_tag, marker="target"):
    """Source image (busybox + a shared random blob) plus a derived image built
    FROM it (adding /marker), each as a single-service composition. The shared
    lower layers are byte-identical, so a delta between them prunes them.

    Returns ((src_manifests, src_images), (derived_manifests, derived_images),
    derived_tar, blob_sha)."""
    ctx = os.path.join(work, "ctx-" + src_tag)
    os.makedirs(ctx)
    blob_sha = _write_blob(os.path.join(ctx, "blob"), BLOB_SIZE)
    source_manifests, source_images, _ = _image_composition(
        work, src_tag, _BUSYBOX_BLOB, ctx
    )
    derived_manifests, derived_images, derived_tar = _image_composition(
        work, derived_tag, f"FROM {src_tag}\nRUN echo {marker} > /marker\n", ctx
    )
    return (
        (source_manifests, source_images),
        (derived_manifests, derived_images),
        derived_tar,
        blob_sha,
    )


def _build_source_and_similar(work, src_tag, tgt_tag):
    """Source/target images that each COPY a big blob differing only in the first
    4 KiB -- distinct layers (not prunable) but ~identical bytes, ideal for xdelta3.

    Returns ((src_manifests, src_images), (tgt_manifests, tgt_images), tgt_blob)."""
    src_ctx = os.path.join(work, "src_ctx-" + src_tag)
    tgt_ctx = os.path.join(work, "tgt_ctx-" + tgt_tag)
    os.makedirs(src_ctx)
    os.makedirs(tgt_ctx)
    blob_v1 = os.path.join(src_ctx, "blob")
    blob_v2 = os.path.join(tgt_ctx, "blob")
    _write_blob(blob_v1, BLOB_SIZE)
    shutil.copy(blob_v1, blob_v2)
    with open(blob_v2, "r+b") as f:
        f.write(os.urandom(4 * 1024))
    source_manifests, source_images, _ = _image_composition(
        work, src_tag, _BUSYBOX_BLOB, src_ctx
    )
    target_manifests, target_images, _ = _image_composition(
        work, tgt_tag, _BUSYBOX_BLOB, tgt_ctx
    )
    return (source_manifests, source_images), (target_manifests, target_images), blob_v2


def _gen_full_artifact(gen, artifact_name, manifests_dir, images_dir, out):
    subprocess.check_call(
        [
            gen,
            "--artifact-name",
            artifact_name,
            "--device-type",
            DEVICE_TYPE,
            "--output-path",
            out,
            "--manifests-dir",
            manifests_dir,
            "--images-dir",
            images_dir,
            "--project-name",
            PROJECT_NAME,
        ]
    )
    return out


def _gen_delta_artifact(
    gen_delta, source_artifact, target_artifact, artifact_name, out, layer_deltas
):
    cmd = [
        gen_delta,
        "--artifact-name",
        artifact_name,
        "--output-path",
        out,
    ]
    if layer_deltas:
        cmd.append("--layer-deltas")
    cmd += [source_artifact, target_artifact]
    # gen_delta-docker-compose uses mender-artifact and (for --layer-deltas) xdelta3 from PATH.
    subprocess.check_call(cmd)
    return out


# ---------------------------------------------------------------------------
# Deploy helpers
# ---------------------------------------------------------------------------


def _get_device_id(devauth):
    devices = devauth.get_devices_status("accepted")
    assert len(devices) == 1
    return devices[0]["id"]


def _deploy_full(
    devauth, deploy, device_id, gen, manifests_dir, images_dir, capture_to
):
    """Deploy a full docker-compose composition (base module). Captures the exact
    generated artifact so the delta can be generated against it."""

    def make_artifact(filename, artifact_name):
        _gen_full_artifact(gen, artifact_name, manifests_dir, images_dir, filename)
        shutil.copy(filename, capture_to)
        return filename

    deployment_id, _ = common_update_procedure(
        verify_status=True,
        devices=[device_id],
        make_artifact=make_artifact,
        devauth=devauth,
        deploy=deploy,
    )
    deploy.check_expected_status("finished", deployment_id)
    deploy.check_expected_statistics(deployment_id, "success", 1)
    return deployment_id


def _deploy_delta(
    devauth,
    deploy,
    device_id,
    gen_delta,
    source_artifact,
    target_artifact,
    layer_deltas,
    expect="success",
    capture_to=None,
):
    def make_artifact(filename, artifact_name):
        _gen_delta_artifact(
            gen_delta,
            source_artifact,
            target_artifact,
            artifact_name,
            filename,
            layer_deltas,
        )
        if capture_to:
            shutil.copy(filename, capture_to)
        return filename

    deployment_id, _ = common_update_procedure(
        verify_status=True,
        devices=[device_id],
        make_artifact=make_artifact,
        devauth=devauth,
        deploy=deploy,
    )
    deploy.check_expected_status("finished", deployment_id)
    if expect is not None:
        deploy.check_expected_statistics(deployment_id, expect, 1)
    return deployment_id


# ---------------------------------------------------------------------------
# Delta artifact structural inspection
# ---------------------------------------------------------------------------


def _dump_delta_images(artifact, dest):
    """Dump and unpack a delta artifact's images.tar.gz. Returns the images dir."""
    files_dir = os.path.join(dest, "files")
    os.makedirs(files_dir)
    subprocess.check_call(["mender-artifact", "dump", "--files", files_dir, artifact])
    images_targz = os.path.join(files_dir, "images.tar.gz")
    assert os.path.exists(images_targz), "delta artifact has no images.tar.gz"
    with tarfile.open(images_targz, "r:gz") as tf:
        tf.extractall(dest)
    return os.path.join(dest, "images")


def _image_tar_has_empty_layer(image_tar):
    """True if the docker image tarball contains a zero-length layer blob (a layer
    that was pruned because it is shared with the source image)."""
    with tarfile.open(image_tar, "r") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            if member.name == "manifest.json" or member.name.endswith(".json"):
                continue
            if member.size == 0:
                return True
    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.min_mender_client_version("6.0.0")
class TestDeltaDockerCompose(MenderTesting):
    @pytest.mark.skip(
        reason="MEN-10126: gen_delta-docker-compose's prune_image_layers() relies "
        "on GNU `find -printf` and `tar --delete`; on the Alpine/musl CI image the "
        "former is absent (busybox find, nothing pruned) and the latter corrupts "
        "the image tarball (musl GNU tar), so the generator either emits a "
        "non-pruned delta or aborts (xargs exit 123). Re-enable once MEN-10126 is "
        "fixed."
    )
    def test_delta_update_pruned_layers(
        self, delta_device, base_gen_script, delta_gen_script
    ):
        """Happy path without --layer-deltas: shared layers are pruned from the
        target artifact and reconstructed on the device from the local source
        image. Verifies correctness AND that the delta is much smaller."""
        env = delta_device
        device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)
        device_id = _get_device_id(devauth)

        uid = uuid.uuid4().hex[:8]
        src_tag = f"delta-src-{uid}"
        tgt_tag = f"delta-tgt-{uid}"

        with tempfile.TemporaryDirectory() as work:
            # Shared 8 MiB blob layer; target built FROM source so its lower layers
            # are byte-identical and get pruned, leaving only the marker layer.
            (
                (src_manifests, src_images),
                (tgt_manifests, tgt_images),
                _,
                blob_sha,
            ) = _build_source_and_derived(work, src_tag, tgt_tag)

            # Full target artifact (baseline for the size comparison) and captured
            # source artifact (input for the delta).
            source_artifact = os.path.join(work, "source.mender")
            target_artifact = os.path.join(work, "target.mender")
            delta_artifact = os.path.join(work, "delta.mender")
            _gen_full_artifact(
                base_gen_script,
                "delta-target",
                tgt_manifests,
                tgt_images,
                target_artifact,
            )

            _deploy_full(
                devauth,
                deploy,
                device_id,
                base_gen_script,
                src_manifests,
                src_images,
                capture_to=source_artifact,
            )
            _assert_running(device, present=[src_tag])

            _deploy_delta(
                devauth,
                deploy,
                device_id,
                delta_gen_script,
                source_artifact,
                target_artifact,
                layer_deltas=False,
                capture_to=delta_artifact,
            )
            _assert_running(device, present=[tgt_tag], absent=[src_tag])

            # Content check: the reconstructed target image really has both its
            # unique layer (/marker) and the pruned-then-reconstructed shared layer
            # (/blob, restored from the local source image), byte-for-byte.
            cid = _running_container_id(device, tgt_tag)
            assert "target" in device.run(f"docker exec {cid} cat /marker")
            assert _container_file_sha256(device, cid, "/blob") == blob_sha

            # Size check: the delta must be dramatically smaller than the full
            # target because the ~8 MiB shared layer is pruned.
            delta_size = os.path.getsize(delta_artifact)
            target_size = os.path.getsize(target_artifact)
            assert (
                delta_size < 0.25 * target_size
            ), f"delta={delta_size} full_target={target_size}"
            assert (
                target_size - delta_size >= 6 * 1024 * 1024
            ), f"delta={delta_size} full_target={target_size}"

            # Structural check: the pruned shared layer shows up as a zero-length
            # blob inside the delta's image tarball.
            with tempfile.TemporaryDirectory() as inspect:
                images_dir = _dump_delta_images(delta_artifact, inspect)
                image_tars = [
                    os.path.join(images_dir, f)
                    for f in os.listdir(images_dir)
                    if f.endswith(".tar")
                ]
                assert image_tars, "no image tarball in delta"
                assert any(_image_tar_has_empty_layer(t) for t in image_tars)

    @pytest.mark.skip(
        reason="MEN-10122: the device's xdelta3 is built --without-liblzma and "
        "cannot decode the LZMA-secondary vcdiff produced by the host's xdelta3, so "
        "a real --layer-deltas reconstruction fails on-device "
        "(xdelta3: unavailable secondary compressor: LZMA). Re-enable once "
        "MEN-10122 is fixed."
    )
    def test_delta_update_layer_deltas(
        self, delta_device, base_gen_script, delta_gen_script
    ):
        """Happy path with --layer-deltas: a similar-but-not-identical layer is
        shipped as an xdelta3 vcdiff and resolved on-device against the local
        source image. Verifies correctness and that --layer-deltas shrinks the
        artifact vs. the same delta without it (A/B)."""
        env = delta_device
        device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)
        device_id = _get_device_id(devauth)

        uid = uuid.uuid4().hex[:8]
        src_tag = f"delta-src-{uid}"
        tgt_tag = f"delta-tgt-{uid}"

        with tempfile.TemporaryDirectory() as work:
            # Source/target blobs differ only in the first 4 KiB: distinct layers
            # (not prunable) but ~identical bytes, so xdelta3 makes the delta tiny.
            (
                (src_manifests, src_images),
                (tgt_manifests, tgt_images),
                blob_v2,
            ) = _build_source_and_similar(work, src_tag, tgt_tag)

            source_artifact = os.path.join(work, "source.mender")
            target_artifact = os.path.join(work, "target.mender")
            delta_with = os.path.join(work, "delta_with.mender")
            delta_without = os.path.join(work, "delta_without.mender")
            _gen_full_artifact(
                base_gen_script,
                "delta-target",
                tgt_manifests,
                tgt_images,
                target_artifact,
            )

            _deploy_full(
                devauth,
                deploy,
                device_id,
                base_gen_script,
                src_manifests,
                src_images,
                capture_to=source_artifact,
            )
            _assert_running(device, present=[src_tag])

            # A/B: same pair, with and without --layer-deltas.
            _gen_delta_artifact(
                delta_gen_script,
                source_artifact,
                target_artifact,
                "delta-without",
                delta_without,
                layer_deltas=False,
            )

            _deploy_delta(
                devauth,
                deploy,
                device_id,
                delta_gen_script,
                source_artifact,
                target_artifact,
                layer_deltas=True,
                capture_to=delta_with,
            )
            _assert_running(device, present=[tgt_tag], absent=[src_tag])

            # Content check: xdelta3 decoded the delta'd layer to the exact target
            # bytes -- the running image's /blob must equal blob_v2 byte-for-byte.
            cid = _running_container_id(device, tgt_tag)
            assert _container_file_sha256(device, cid, "/blob") == _sha256_file(blob_v2)

            with_size = os.path.getsize(delta_with)
            without_size = os.path.getsize(delta_without)
            assert (
                with_size < 0.25 * without_size
            ), f"delta_with={with_size} delta_without={without_size}"

            # Structural check: the --layer-deltas artifact carries a vcdiff triple
            # and no full image tarball for the delta'd image.
            with tempfile.TemporaryDirectory() as inspect:
                images_dir = _dump_delta_images(delta_with, inspect)
                names = os.listdir(images_dir)
                assert any(
                    n.endswith(".vcdiff") for n in names
                ), f"delta_with images/ contents: {names}"
                assert any(
                    n.endswith(".vcdiff~source_image") for n in names
                ), f"delta_with images/ contents: {names}"
                assert any(
                    n.endswith(".vcdiff~source_layers") for n in names
                ), f"delta_with images/ contents: {names}"
                # The full image tarball is replaced by the vcdiff, not shipped.
                assert not any(
                    n.endswith(".tar") for n in names
                ), f"delta_with images/ contents: {names}"

    def test_delta_rollback_on_failure(
        self, delta_device, base_gen_script, delta_gen_script
    ):
        """A failing delta (target composition never becomes healthy) rolls back to
        the previously-committed delta composition.

        A meaningful rollback requires a prior committed delta in the delta store,
        so the chain is: source (base) -> delta_ok (A) -> delta_fail (B). B is a
        *distinct* image with a failing healthcheck, so after rollback we can assert
        A is running and B is gone.
        """
        env = delta_device
        device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)
        device_id = _get_device_id(devauth)

        uid = uuid.uuid4().hex[:8]
        src_tag = f"delta-src-{uid}"
        a_tag = f"delta-a-{uid}"
        b_tag = f"delta-b-{uid}"

        with tempfile.TemporaryDirectory() as work:
            (
                (src_manifests, src_images),
                (a_manifests, a_images),
                _,
                _,
            ) = _build_source_and_derived(work, src_tag, a_tag, marker="a")
            # Composition B: a distinct image (built FROM A) with a failing
            # healthcheck, so its deploy never becomes healthy and never commits.
            b_ctx = os.path.join(work, "b_ctx")
            os.makedirs(b_ctx)
            b_manifests, b_images, _ = _image_composition(
                work,
                b_tag,
                f"FROM {a_tag}\nRUN echo b > /marker-b\n",
                b_ctx,
                compose_extra=FAILING_HEALTHCHECK,
            )

            source_artifact = os.path.join(work, "source.mender")
            a_artifact = os.path.join(work, "a.mender")
            b_artifact = os.path.join(work, "b.mender")
            _gen_full_artifact(
                base_gen_script, "comp-a", a_manifests, a_images, a_artifact
            )
            _gen_full_artifact(
                base_gen_script, "comp-b", b_manifests, b_images, b_artifact
            )

            # source (base module)
            _deploy_full(
                devauth,
                deploy,
                device_id,
                base_gen_script,
                src_manifests,
                src_images,
                capture_to=source_artifact,
            )
            # delta_ok: source -> A  (committed in the delta store)
            _deploy_delta(
                devauth,
                deploy,
                device_id,
                delta_gen_script,
                source_artifact,
                a_artifact,
                layer_deltas=False,
            )
            _assert_running(device, present=[a_tag])

            # delta_fail: A -> B (fails healthcheck) -> rollback to A
            deployment_id = _deploy_delta(
                devauth,
                deploy,
                device_id,
                delta_gen_script,
                a_artifact,
                b_artifact,
                layer_deltas=False,
                expect="failure",
            )

        # Failed because B never became healthy (its healthcheck fails).
        _assert_deployment_log_contains(
            deploy, device_id, deployment_id, "Timeout reached"
        )
        # Rolled back to composition A (running); the failed B is gone.
        _assert_running(device, present=[a_tag], absent=[b_tag])

    def test_delta_first_delta_rollback_preserves_source(
        self, delta_device, base_gen_script, delta_gen_script
    ):
        """A failed *first* delta -- one deployed when the delta store holds no
        previously-committed delta -- must leave the device unmodified: the base
        source composition keeps running.

        This is the boundary test_delta_rollback_on_failure steps around. There the
        rollback target is a prior committed delta (A) in the delta store; here the
        delta store has no prior state, and the source composition lives in the
        *separate* base-module store. A failed update must be a no-op for the device
        as a whole, so after rollback the source composition must still be running
        and the failed target must never have taken over.
        """
        env = delta_device
        device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)
        device_id = _get_device_id(devauth)

        uid = uuid.uuid4().hex[:8]
        src_tag = f"delta-src-{uid}"
        b_tag = f"delta-b-{uid}"

        with tempfile.TemporaryDirectory() as work:
            # Source composition (busybox + a random blob), deployed via the base
            # module -- the only thing installed before the delta.
            ctx = os.path.join(work, "ctx-" + src_tag)
            os.makedirs(ctx)
            _write_blob(os.path.join(ctx, "blob"), BLOB_SIZE)
            src_manifests, src_images, _ = _image_composition(
                work, src_tag, _BUSYBOX_BLOB, ctx
            )
            # Composition B: a distinct image built FROM source, with a failing
            # healthcheck so its deploy never becomes healthy and never commits.
            b_ctx = os.path.join(work, "b_ctx")
            os.makedirs(b_ctx)
            b_manifests, b_images, _ = _image_composition(
                work,
                b_tag,
                f"FROM {src_tag}\nRUN echo b > /marker-b\n",
                b_ctx,
                compose_extra=FAILING_HEALTHCHECK,
            )

            source_artifact = os.path.join(work, "source.mender")
            b_artifact = os.path.join(work, "b.mender")
            _gen_full_artifact(
                base_gen_script, "comp-b", b_manifests, b_images, b_artifact
            )

            # source (base module) -- the device's only installed composition
            _deploy_full(
                devauth,
                deploy,
                device_id,
                base_gen_script,
                src_manifests,
                src_images,
                capture_to=source_artifact,
            )
            _assert_running(device, present=[src_tag])

            # first delta: source -> B (fails healthcheck) -> rollback
            deployment_id = _deploy_delta(
                devauth,
                deploy,
                device_id,
                delta_gen_script,
                source_artifact,
                b_artifact,
                layer_deltas=False,
                expect="failure",
            )

        # Failed because B never became healthy (its healthcheck fails).
        _assert_deployment_log_contains(
            deploy, device_id, deployment_id, "Timeout reached"
        )
        # A failed update must not modify the device: the base source composition
        # is still running and the failed B never took over.
        _assert_running(device, present=[src_tag], absent=[b_tag])

    def test_delta_missing_xdelta3(
        self, delta_device, base_gen_script, delta_gen_script
    ):
        """Resolving a --layer-deltas artifact needs xdelta3 on the device. Without
        it the install fails and the running source composition is untouched."""
        env = delta_device
        device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)
        device_id = _get_device_id(devauth)

        uid = uuid.uuid4().hex[:8]
        src_tag = f"delta-src-{uid}"
        tgt_tag = f"delta-tgt-{uid}"

        with tempfile.TemporaryDirectory() as work:
            (
                (src_manifests, src_images),
                (tgt_manifests, tgt_images),
                _,
            ) = _build_source_and_similar(work, src_tag, tgt_tag)

            source_artifact = os.path.join(work, "source.mender")
            target_artifact = os.path.join(work, "target.mender")
            _gen_full_artifact(
                base_gen_script,
                "delta-target",
                tgt_manifests,
                tgt_images,
                target_artifact,
            )

            _deploy_full(
                devauth,
                deploy,
                device_id,
                base_gen_script,
                src_manifests,
                src_images,
                capture_to=source_artifact,
            )
            _assert_running(device, present=[src_tag])

            # Remove xdelta3 so the vcdiff cannot be resolved.
            device.run("rm -f /usr/bin/xdelta3")

            deployment_id = _deploy_delta(
                devauth,
                deploy,
                device_id,
                delta_gen_script,
                source_artifact,
                target_artifact,
                layer_deltas=True,
                expect="failure",
            )

        # Failed while resolving the layer delta (xdelta3 unavailable on device).
        _assert_deployment_log_contains(
            deploy, device_id, deployment_id, "failed to resolve layer deltas"
        )
        # Source composition remains running (delta install failed before swapping).
        _assert_running(device, present=[src_tag], absent=[tgt_tag])

    def test_delta_failed_resolution(
        self, delta_device, base_gen_script, delta_gen_script
    ):
        """If delta resolution errors out (xdelta3 -d fails), extract_images fails,
        the deployment fails, and the source composition is left intact -- no
        half-reconstructed image is loaded."""
        env = delta_device
        device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)
        device_id = _get_device_id(devauth)

        uid = uuid.uuid4().hex[:8]
        src_tag = f"delta-src-{uid}"
        tgt_tag = f"delta-tgt-{uid}"

        with tempfile.TemporaryDirectory() as work:
            (
                (src_manifests, src_images),
                (tgt_manifests, tgt_images),
                _,
            ) = _build_source_and_similar(work, src_tag, tgt_tag)

            source_artifact = os.path.join(work, "source.mender")
            target_artifact = os.path.join(work, "target.mender")
            _gen_full_artifact(
                base_gen_script,
                "delta-target",
                tgt_manifests,
                tgt_images,
                target_artifact,
            )

            _deploy_full(
                devauth,
                deploy,
                device_id,
                base_gen_script,
                src_manifests,
                src_images,
                capture_to=source_artifact,
            )
            _assert_running(device, present=[src_tag])

            # Wrap xdelta3 so version discovery passes but decoding fails.
            with tempfile.TemporaryDirectory() as script_dir:
                wrapper = os.path.join(script_dir, "xdelta3")
                with open(wrapper, "w") as f:
                    f.write(
                        "#!/bin/sh\n"
                        'if [ "$1" = "-V" ]; then exec /usr/bin/xdelta3.real -V; fi\n'
                        'if [ "$1" = "-d" ]; then echo "simulated decode failure" 1>&2; exit 1; fi\n'
                        'exec /usr/bin/xdelta3.real "$@"\n'
                    )
                os.chmod(wrapper, 0o755)
                device.run("mv /usr/bin/xdelta3 /usr/bin/xdelta3.real")
                device.put("xdelta3", local_path=script_dir, remote_path="/usr/bin/")
                device.run("chmod +x /usr/bin/xdelta3")

            deployment_id = _deploy_delta(
                devauth,
                deploy,
                device_id,
                delta_gen_script,
                source_artifact,
                target_artifact,
                layer_deltas=True,
                expect="failure",
            )

        # Failed at layer-delta resolution: xdelta3 -d returns non-zero.
        _assert_deployment_log_contains(
            deploy, device_id, deployment_id, "failed to resolve layer deltas"
        )
        _assert_running(device, present=[src_tag], absent=[tgt_tag])
