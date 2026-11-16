# Supply-chain security and release verification

## Trust boundaries

Pull requests run deterministic lockfile checks, Python and npm advisory audits,
workflow analysis, secret scanning, and filesystem misconfiguration scanning.
Only a protected `v*` tag can publish images. The publish workflow has separate
package and OIDC permissions and builds the exact tagged commit.

Python installs use [`requirements.txt`](../../requirements.txt) and
[`requirements-dev.txt`](../../requirements-dev.txt). Node projects use their
committed `package-lock.json` files with `npm ci`; `npm install` is not used in
CI. Dependency updates must regenerate the corresponding lockfile and pass
license and vulnerability checks.

## Artifact integrity

Buildx emits OCI SBOM and provenance attestations. Each GHCR image is signed
with Cosign keyless signing through GitHub OIDC. The workflow verifies the
signature immediately after signing and attaches a GitHub artifact attestation.
The signing certificate identity is restricted to this repository's publish
workflow.

Verify a released image (replace the digest with the release digest):

```sh
cosign verify ghcr.io/FL-Blockchain-Project-Major/trustfl/api@sha256:<digest> \
  --certificate-identity-regexp \
  'https://github.com/FL-Blockchain-Project-Major/trustfl/.github/workflows/.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
docker buildx imagetools inspect \
  ghcr.io/FL-Blockchain-Project-Major/trustfl/api@sha256:<digest>
```

Verification must happen before deployment. Deployments should reference image
digests, not moving tags, and the admission policy should require a valid
Cosign certificate and provenance attestation.

## Response and rotation

The security team triages high and critical dependency findings immediately and
opens a tracked remediation issue for every accepted risk. If a signing identity
or workflow is compromised, stop deployments, revoke the affected workflow
trust policy, quarantine the affected digests, rotate the OIDC/KMS policy, and
publish a replacement release. Keyless signing avoids a long-lived private key;
any future KMS-backed key must be rotated at least annually and after suspected
exposure.

Secret findings are treated as compromised credentials: revoke first, preserve
the finding metadata without copying the secret, then remove the artifact from
history using the repository incident procedure. Secret scanning and Trivy
must remain enabled on every protected branch.

## Limitations

The release workflow's signing and registry attestation require GitHub OIDC,
GHCR write permission, and a trusted protected tag. Local builds do not claim
to have GitHub provenance or a valid release signature. Advisory databases and
scanner images are external inputs; their pinned actions and explicit severity
thresholds make failures reproducible, but cannot prove that an undisclosed
vulnerability does not exist.
