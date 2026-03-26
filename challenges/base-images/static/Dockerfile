# Build: docker buildx build --build-arg FLAG="infodays{...}" --output type=local,dest=./dist .
# Output: ./dist/challenge.zip (contains flag.txt at zip root)
# This Dockerfile produces NO runtime image.

# Stage 1: Builder
FROM python:3.11-alpine AS builder
ARG FLAG
# Validate FLAG is non-empty at build time
RUN test -n "${FLAG}" || \
    (echo "ERROR: FLAG build argument is required and must not be empty." >&2 && exit 1)

RUN apk add --no-cache zip

WORKDIR /build
# Write flag.txt with the FLAG value
RUN echo -n "${FLAG}" > flag.txt
# Create the archive with flag.txt at the zip root
RUN zip challenge.zip flag.txt
# Copy artifact to /out/
RUN mkdir -p /out && cp challenge.zip /out/

# Stage 2: Export (scratch final stage for artifact extraction)
FROM scratch
# Export /out contents to the host via --output type=local,dest=./dist
COPY --from=builder /out /
