"""Static-file storage tuned for the bundled third-party assets.

Some vendored bundles reference source maps or other optional files that are
not shipped with the package. Django's manifest storage treats those missing
references as fatal during ``collectstatic``. This subclass keeps hashing and
compression, but leaves an unresolved reference untouched instead of failing a
deployment.
"""

from whitenoise.storage import CompressedManifestStaticFilesStorage


class LenientCompressedManifestStaticFilesStorage(CompressedManifestStaticFilesStorage):
    def url_converter(self, name, hashed_files, template=None):
        converter = super().url_converter(name, hashed_files, template)

        def lenient_converter(matchobj):
            try:
                return converter(matchobj)
            except ValueError:
                return matchobj.groupdict()["matched"]

        return lenient_converter
