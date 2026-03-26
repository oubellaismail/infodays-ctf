# Contract: Static Challenge Archive Builder Interface

**Feature**: 004-base-images-docr | **Date**: 2026-03-25

---

## Static Builder (`challenges/base-images/static/Dockerfile`)

The static builder is a build-only image — it produces a `challenge.zip` artifact and has no runtime behaviour.

### Build Command

```sh
docker buildx build \
  --build-arg FLAG="infodays{...}" \
  --output type=local,dest=./dist \
  challenges/base-images/static/
```

### Build Arguments

| Argument | Required | Validation | Description |
|----------|----------|------------|-------------|
| `FLAG` | **YES** | Non-empty string | The flag to embed in the archive. Build fails with a clear error if absent or empty. |

### Output

| Path | Description |
|------|-------------|
| `./dist/challenge.zip` | The challenge archive, ready for upload to CTFd Files section |

### Archive Structure

```
challenge.zip
└── flag.txt          ← Contains the flag value (the FLAG build argument)
```

`flag.txt` MUST be at the zip root. Additional challenge files (provided by the challenge author) may also be included in the zip.

### Failure Modes

| Condition | Behaviour |
|-----------|-----------|
| `FLAG` build-arg missing | Build exits non-zero with message: `"ERROR: FLAG build argument is required"` |
| `FLAG` build-arg is empty string | Build exits non-zero with the same error |

### No Runtime Image

The static builder MUST NOT produce a runnable container image. Its only output is the `./dist/challenge.zip` file on the host. The final Dockerfile stage uses `FROM scratch` to ensure no image can be accidentally pushed or deployed.

### Example

```sh
# Produce a challenge archive for a forensics challenge
docker buildx build \
  --build-arg FLAG="infodays{s3cr3t_fl4g}" \
  --output type=local,dest=./dist \
  challenges/base-images/static/

# Verify output
unzip -p ./dist/challenge.zip flag.txt
# → infodays{s3cr3t_fl4g}
```
