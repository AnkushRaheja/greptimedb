#!/usr/bin/env bash
# Usage: hash_artifacts.sh <artifact dir>
cd "$1" || exit 1
echo "# Artifact hashes and identities"
echo "# generated $(date -u +%Y-%m-%dT%H:%M:%SZ) at pinned commit 2b596fd52df31dcad779794877a296de7746f736"
echo
echo "## sha256"
sha256sum Dockerfile test.patch solution.patch
echo
echo "## identity (file bytes lines crlf_lines bom trailing_newline)"
for f in Dockerfile test.patch solution.patch; do
    bytes=$(stat -c %s "$f"); lines=$(wc -l < "$f"); crlf=$(grep -c $'\r$' "$f")
    bom=$(head -c 3 "$f" | od -An -tx1 | tr -d ' \n'); [ "$bom" = "efbbbf" ] && bom=yes || bom=no
    tn=$(tail -c 1 "$f" | od -An -tx1 | tr -d ' \n'); [ "$tn" = "0a" ] && tn=yes || tn=no
    nonascii=$(LC_ALL=C grep -c -P '[^\x00-\x7F]' "$f")
    echo "$f bytes=$bytes lines=$lines crlf_lines=$crlf bom=$bom trailing_newline=$tn non_ascii_lines=$nonascii"
done
echo
for p in test.patch solution.patch; do
    echo "## changed files: $p"
    grep -E '^diff --git ' "$p" | sed 's#^diff --git a/\([^ ]*\) b/.*#\1#' | while read -r path; do
        mode=$(awk -v p="$path" '$0 ~ "^diff --git a/"p" " {f=1; next} f && /^(new file mode|deleted file mode|index)/ {print; exit}' "$p")
        added=$(awk -v p="$path" '$0 ~ "^diff --git a/"p" " {f=1; next} /^diff --git / {f=0} f && /^\+/ && !/^\+\+\+/ {n++} END {print n+0}' "$p")
        removed=$(awk -v p="$path" '$0 ~ "^diff --git a/"p" " {f=1; next} /^diff --git / {f=0} f && /^-/ && !/^---/ {n++} END {print n+0}' "$p")
        echo "$path +$added -$removed ${mode}"
    done
    echo
done
