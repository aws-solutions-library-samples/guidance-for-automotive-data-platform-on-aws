"""Pinned set of scan-excluded-but-shipped files accepted for ADP.

Per-repo DATA, deliberately NOT vendored: it is absent from the publish-toolkit sync
anchor, so editing it never trips the drift check. Consumed at runtime by the vendored
`scripts/lib/test_publish_scan_exclude_invariant.py`.

This set is a RATCHET. Entries should only ever be REMOVED, as files get cleaned up or
publish-excluded. Adding one means accepting that a file ships without the scanner ever
reading it — the mechanism that produced four exposures across this portfolio in two days
(see ~/.kiro/steering/public-mirror-publish.md § "The exclusion-mechanism rule").

ADP's posture is the strongest of the three accelerators: it publish-excludes the entire
publish machinery (publish-to-github.sh, secret-scan.py, test_secret_scan.py, the scan
config and the exclude file), so none of those appears here — unlike CMS, which needed 49
entries. Only 3 of ADP's 31 scan-excluded-but-shipped files are non-binary; the other 28
are images, fonts and parquet fixtures that are scan-excluded for size and encoding, not
to hide content.

Created 2026-08-04 when the invariant test was canonicalized into the toolkit and ported
here, so ADP's clean posture is asserted on every push rather than merely true today.
"""

BASELINE = {
    # Denylist file: its patterns necessarily name what they exclude. Scanned-excluded to
    # stop it self-tripping. Reviewed — carries no real account ID, unlike CMS's, whose
    # .gitignore leaked one to the public mirror.
    ".gitignore",
    # Required public-facing boilerplate. Scan-excluded because the AWS-standard text
    # mentions amazon.com URLs that trip the internal-email/hostname patterns.
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
}
