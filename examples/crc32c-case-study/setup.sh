#!/usr/bin/env bash
# Recreate the crc32c case study: clone google/crc32c at a pinned commit, add reqtrace's
# config and requirements, and apply the trace annotations (comments only).
#
#   ./setup.sh [target-dir]        default: ./crc32c
#   cd crc32c && reqtrace verify && reqtrace matrix && reqtrace gaps
#
# Needs git, cmake, ninja, clang and LLVM tools (llvm-profdata, llvm-cov); clang >= 18 for MC/DC.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
target="${1:-crc32c}"
commit=2bbb3be42e20a0e6c0f7b39dc07dc863d9ffbc07   # "Fix CMake 4.0 compatibility. (#68)"

git clone --quiet https://github.com/google/crc32c.git "$target"
cd "$target"
git checkout --quiet "$commit"
git submodule update --init --quiet third_party/googletest   # benchmark/glog are not needed
cp "$here/.reqtrace.yaml" .
mkdir -p requirements && cp "$here/requirements/crc32c.yaml" requirements/
git apply "$here/annotations.patch"
printf '.reqtrace/runs/\n.reqtrace/build/\n' >> .git/info/exclude
git checkout --quiet -b reqtrace-case-study
git add -A
git -c user.name="reqtrace setup" -c user.email="setup@reqtrace.invalid" \
  commit --quiet -m "Add reqtrace config, requirements and trace annotations"
echo "Ready: $(pwd)"
echo "Next:  cd $target && reqtrace verify && reqtrace matrix && reqtrace gaps"
