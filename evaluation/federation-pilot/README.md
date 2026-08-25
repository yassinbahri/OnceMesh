# External federation pilot operator runbook

This directory contains deliberately incomplete origin and receiver templates.
Replace every angle-bracket placeholder; preflight rejects unresolved values.
Keep the completed manifests in each operator's own environment.

## 1. Generate identities

The origin generates separate availability and receipt identities. The receiver
generates a request identity. Use new paths each time:

```powershell
oncemesh-federation keygen --peer-id org-a --purpose availability `
  --private-seed-file .\secrets\availability.seed `
  --public-identity-file .\public\availability.identity.json
```

```powershell
oncemesh-federation keygen --peer-id org-b --purpose request `
  --private-seed-file .\secrets\request.seed `
  --public-identity-file .\public\request.identity.json
```

Move the seed files into the local secret manager or an ACL-restricted
supervisor location. Exchange only public identity files through an authenticated
out-of-band channel. Verify the displayed key identifiers independently.

## 2. Package the origin result

The production receipt must already be signed. Supply every artifact by its
manifest name. Both publication flags are intentionally required:

```powershell
oncemesh-federation package-publication `
  --action .\action.json `
  --result-manifest .\result.json `
  --receipt .\receipt.json `
  --receipt-identity .\public\receipt.identity.json `
  --artifact result=.\artifacts\result.txt `
  --classification public `
  --confirm-publication-review `
  --output .\publications\pilot-result.json
```

## 3. Prepare manifests and secrets

Copy the appropriate template and replace all placeholders. Load each seed into
the environment without placing its value in shell history:

```powershell
$env:ONCEMESH_AVAILABILITY_SEED = (Get-Content -Raw -LiteralPath .\secrets\availability.seed).Trim()
```

```powershell
$env:ONCEMESH_REQUEST_SEED = (Get-Content -Raw -LiteralPath .\secrets\request.seed).Trim()
```

## 4. Run offline preflight

These commands make no peer request:

```powershell
oncemesh-federation preflight-origin --manifest .\origin-pilot.json
```

```powershell
oncemesh-federation preflight-receiver --manifest .\receiver-pilot.json
```

Exchange the public preflight reports and compare identities and intended
digests before opening the pilot endpoint.

## 5. Run the pilot

The origin starts first:

```powershell
oncemesh-federation serve --manifest .\origin-pilot.json
```

The receiver runs exactly one new probe ID:

```powershell
oncemesh-federation probe --manifest .\receiver-pilot.json
```

Follow the acceptance and abort conditions in
`spec/federation-external-pilot-v0.md`. Clear the seed environment variables
when the processes stop.
