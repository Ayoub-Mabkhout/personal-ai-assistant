# Signed companion releases

The source-check workflow runs isolated Python tests and the path/content
publication guard on Linux and Windows for branch pushes and pull requests. It
does not receive release secrets. Tests use temporary stores and fake providers;
they do not scan a mailbox, insert live calendar entries, or call paid models.

The release workflow accepts stable tags such as `v0.7.0`. Before a secret-bearing
job starts, it requires the tag's commit to be in the repository's default branch
history and checks that Android `versionName` matches the tag. Increment both
`versionCode` and `versionName` in `apps/android/AndroidManifest.xml` for changed
APK bytes. The initial GitHub release `v0.7.0` uses code `7` and name `0.7.0`.

The Windows build uses official Android SDK platform 35/build-tools 35.0.0,
Temurin JDK 17, the pinned Gradle/AGP project, and the checksum-verified ARM64 Vosk
runtime from `scripts/fetch_vosk_runtime.py --release`. Upstream model and library
licenses are included in the APK. Signing uses the existing persistent PKCS12 key
and alias `companion`; CI refuses to generate a replacement signing identity.

## Repository setup

Store these encrypted Actions secrets in the release repository:

| Secret | Value |
| --- | --- |
| `ANDROID_SIGNING_KEY_BASE64` | Base64 bytes of the existing `companion.p12` |
| `ANDROID_SIGNING_PASSWORD` | Its exact single-line keystore password |
| `FIREBASE_ANDROID_CONFIG_BASE64` | Base64 Android `google-services.json` client configuration |
| `COMPANION_PUBLICATION_URL` | Complete HTTPS URL ending in `/companion/v1/releases/artifact` |
| `COMPANION_PUBLICATION_TOKEN` | The dedicated artifact-publishing bearer token |

Keep protected originals outside OneDrive and the checkout. Do not commit signing
files, Firebase configuration, deployment addresses, or tokens. Runner staging is
restricted to `RUNNER_TEMP/personal-assistant-release-secrets`, removed in an
`always()` step, and excluded from the uploaded artifact. Only the exact normal
APK and its `.release.json` sidecar are transferred between release jobs.

Protect the default branch and version tags with GitHub repository rulesets:
restrict version tag creation/update/deletion to authorized maintainers, require
source checks before default-branch merges, and disable bypasses where practical.
The workflow's ancestry check enforces source membership; GitHub permissions and
tag rules determine who may request a release. A fork's source-check workflow
remains usable, but its release workflow skips secret-bearing jobs.

## Publish and recover

After reviewing and merging the completed feature and passing the publication
guard, push the source commit and then the matching version tag. The workflow
verifies the signed package/version with the official SDK, rejects diagnostic
classes, private audio, foreign native ABIs, unexpected assets and debuggable or
instrumentation manifests, and enforces the existing app's 50 MiB updater limit.

Publication first creates a GitHub draft containing the APK and release JSON. It
then sends those exact APK bytes to the narrow server endpoint using `PUT`, with
the manifest in the base64 `X-Release-Manifest` header and the dedicated token in
`Authorization: Bearer ...`. HTTPS redirects are rejected so the token cannot be
forwarded to another location. The build checks the signing identity through
`apksigner`; the server checks hashes, version immutability, ZIP validity and
diagnostic guards, installs the artifact, and records the durable update
event. Only after that succeeds does the workflow publish the GitHub draft.

If publication fails, inspect the failed step and the private server receipt,
then rerun the failed publish job while the signed build artifact is retained.
An existing GitHub release must have byte-identical APK and JSON assets; the
workflow never clobbers release assets. If new bytes are needed, increment the
Android version and use a new tag. Server retries for an identical release are
idempotent. A successful publication records server acceptance; handset delivery,
installation, real microphone behavior, battery and sustained lock-screen use
still need device verification.

Actions are pinned to full commit SHAs verified in their official repositories:
[checkout v6.0.2](https://github.com/actions/checkout/releases/tag/v6.0.2),
[setup-python v7.0.0](https://github.com/actions/setup-python/releases/tag/v7.0.0),
[setup-java v6.0.0](https://github.com/actions/setup-java/releases/tag/v6.0.0),
[upload-artifact v6.0.0](https://github.com/actions/upload-artifact/releases/tag/v6.0.0),
and [download-artifact v7.0.0](https://github.com/actions/download-artifact/releases/tag/v7.0.0).
This follows GitHub's guidance on [immutable action references and least-privilege
workflow permissions](https://docs.github.com/en/actions/reference/security/secure-use).
