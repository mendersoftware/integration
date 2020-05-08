import io
import os
import random
import tarfile
import hashlib
import json


class Artifact:
    """
    Artifact provides a very simplistic implementation of mender artifact
    that allows creating simple buffered artifact file objects that
    resides in memory.
    """

    _dummySHA = "%064d" % 0

    def __init__(self, artifact_name, device_types, payload=None):
        """
        :param artifact_name: name of the artifact (str)
        :param device_types:  list of compatible device types (list)
        :param payload:       optional payload to initialize the payload
                              section (file/io.IOBase, str, bytes)
        """
        if not isinstance(device_types, list):
            raise ValueError("device_types must be a list of strings")

        self._filenames = ["version", "header.tar.gz"]
        self._payloads = {}
        self._provides = {"header-info": {"artifact_name": artifact_name}}
        self._depends = {"header-info": {"device_type": device_types}}
        self._payload_types = {}
        self._shasums = {}

        if payload is not None:
            self.add_payload(payload)

    def add_payload(self, fd, payload_type="rootfs_image", depends=None, provides=None):
        """
        add_payload adds another payload to the payload section.
        :param fd:           "file descriptor" contains the payload
                             (io.IOBase/file, str, bytes)
        :param payload_type: type of payload contained in fd (str)
        :param depends:      optional depends for this payload (dict)
        :param provides:     optional provides for this payload (dict)
        """
        if isinstance(fd, str):
            fd = io.BytesIO(fd.encode())
        elif isinstance(fd, bytes):
            fd = io.BytesIO(fd)
        elif not isinstance(fd, io.IOBase):
            raise ValueError("fd must be an instance of either io.FileIO, str or bytes")
        filename = "data/%04d/%s" % (
            len(self._payloads),
            getattr(fd, "name", "rootfs-%04d.ext4" % random.randint(0, 10000)),
        )

        self._filenames.append(filename)
        self._payloads[filename] = fd
        self._payload_types[filename] = payload_type
        if isinstance(depends, dict):
            self._depends[filename] = depends
        if isinstance(provides, dict):
            self._provides[filename] = provides

    def _compute_checksum(self, filename, fd):
        fd.seek(0)
        BUFSIZE = 1024 * 1024
        sha = hashlib.sha256()
        while True:
            # Digest a MiB at the time
            buf = fd.read(BUFSIZE)
            if len(buf) == 0:
                break
            sha.update(buf)

        self._shasums[filename] = sha.hexdigest()
        size = fd.tell()
        fd.seek(0)
        return size

    def _initialize_manifest(self):
        """
        This is sort of cheating: this function initialize the manifest
        bogus checksums. Later, _complete_manifest will seek to the stored
        checksum offsets and overwrite these checksums with the correct
        one.
        """
        tmp_manifest = io.BytesIO()
        self._manifest_offsets = {}
        for filename in self._filenames[::-1]:
            self._manifest_offsets[filename] = tmp_manifest.tell()
            tmp_manifest.write(("%s  %s\n" % (self._dummySHA, filename)).encode())
        size = tmp_manifest.tell()
        tarhdr = tarfile.TarInfo("manifest")
        tarhdr.size = size
        tmp_manifest.seek(0)
        self._tarfact.addfile(tarhdr, fileobj=tmp_manifest)

    def _complete_manifest(self):
        self._artifact.seek(0)
        rdtar = tarfile.open(fileobj=self._artifact, mode="r")
        manifest_hdr = rdtar.getmember("manifest")
        offset = manifest_hdr.offset_data
        for filename in self._filenames[::-1]:
            offset_sha = offset + self._manifest_offsets[filename]
            self._artifact.seek(offset_sha)
            self._artifact.write(self._shasums[filename].encode())

    def _add_payloads(self):
        """
        Adds all the stored payload to artifact.
        Each payload is itself a compressed tar.
        """
        filenames = sorted(list(self._payloads.keys()))
        for filename in filenames:
            fd = self._payloads[filename]

            size = fd.seek(0, io.SEEK_END)
            fd.seek(0)

            payload_tarbin = io.BytesIO()
            payload_tar = tarfile.open(fileobj=payload_tarbin, mode="w:gz")
            tarhdr = tarfile.TarInfo(os.path.basename(filename))
            tarhdr.size = size
            payload_tar.addfile(tarhdr, fd)
            payload_tar.close()

            tarhdr = tarfile.TarInfo(os.path.dirname(filename) + ".tar.gz")
            tarhdr.size = payload_tarbin.tell()
            self._compute_checksum(filename, fd)
            payload_tarbin.seek(0)
            self._tarfact.addfile(tarhdr, payload_tarbin)

    def _add_version(self):
        version = {"format": "mender", "version": 3}
        fd = io.BytesIO(json.dumps(version).encode())
        size = self._compute_checksum("version", fd)
        tarhdr = tarfile.TarInfo("version")
        tarhdr.size = size
        self._tarfact.addfile(tarhdr, fd)

    def _add_header(self):
        hdr_tarbin = io.BytesIO()
        hdr_tar = tarfile.open(fileobj=hdr_tarbin, mode="w:gz")
        header_info = {
            "payloads": [
                {
                    "type": self._payload_types[filename]
                    for filename in sorted(self._payloads.keys())
                }
            ]
        }
        header_info["artifact_provides"] = self._provides["header-info"]
        header_info["artifact_depends"] = self._depends["header-info"]
        hdr_info = io.BytesIO(json.dumps(header_info).encode())
        size = hdr_info.seek(0, io.SEEK_END)
        hdr_info.seek(0)
        tarhdr = tarfile.TarInfo("header-info")
        tarhdr.size = size
        hdr_tar.addfile(tarhdr, hdr_info)

        for filename in sorted(self._payloads.keys()):
            path_prefix = os.path.join(
                "headers", os.path.basename(os.path.dirname(filename))
            )
            typeinfo = {"type": self._payload_types[filename]}
            if filename in self._depends:
                typeinfo["artifact_depends"] = self._depends[filename]
            if filename in self._provides:
                typeinfo["artifact_provides"] = self._provides[filename]

            # Add type-info to tarfile
            typeinfo_bin = io.BytesIO(json.dumps(typeinfo).encode())
            size = typeinfo_bin.seek(0, io.SEEK_END)
            typeinfo_bin.seek(0)
            typeinfo_hdr = tarfile.TarInfo(os.path.join(path_prefix, "type-info"))
            typeinfo_hdr.size = size
            hdr_tar.addfile(typeinfo_hdr, typeinfo_bin)

            # Add empty meta-data to tarfile
            metadata_hdr = tarfile.TarInfo(name=os.path.join(path_prefix, "meta-data"))
            hdr_tar.addfile(metadata_hdr)

        # Complete tar padding
        hdr_tar.close()
        size = self._compute_checksum("header.tar.gz", hdr_tarbin)
        tarhdr = tarfile.TarInfo("header.tar.gz")
        tarhdr.size = size
        self._tarfact.addfile(tarhdr, hdr_tarbin)

    def make(self):
        """
        make compiles the artifact at the current state and returns a
        file object with the raw binary artifact.
        :returns: artifact (io.BytesIO)
        """
        self._artifact = io.BytesIO()
        self._tarfact = tarfile.open(fileobj=self._artifact, mode="w")
        self._add_version()
        self._initialize_manifest()
        self._add_header()
        self._add_payloads()
        self._complete_manifest()
        self._artifact.seek(0)
        return self._artifact
