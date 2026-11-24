#!/usr/bin/env bash
#
# Remove the testbench. The platform itself is untouched — what it stored
# about these sources (documents, connectors, skills) stays until you delete
# it on the Data page, which is the point: a deleted source should degrade
# gracefully, not disappear.
set -euo pipefail

docker rm -f karag-test-api karag-test-pg karag-test-mysql 2>/dev/null || true
echo "testbench removed. Generated files are still in testbench/build/."
