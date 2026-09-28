#!/usr/bin/env bash
SP=/tmp/claude-0/-home-user-greptimedb/0a7498d9-9500-5f31-9e64-7a1e4b9bc8c6/scratchpad
export PATH=$SP/tools:$PATH CARGO_TARGET_DIR=/home/user/greptimedb-target
cd /home/user/greptimedb || exit 1
PROD="src/common/meta/src/ddl.rs src/common/meta/src/ddl_manager.rs src/common/meta/src/error.rs src/common/meta/src/key.rs src/common/meta/src/metrics.rs"
restore() {
    git checkout -- $PROD && rm -f src/common/meta/src/ddl/drop_logical_tables.rs && git apply $SP/artifacts/solution.patch
}
mkdir -p $SP/mutants
: > $SP/mutants/summary.txt
for m in $(python3 $SP/mutants.py list); do
    restore || { echo "$m RESTORE-FAILED" >> $SP/mutants/summary.txt; exit 1; }
    if ! python3 $SP/mutants.py $m > $SP/mutants/$m.apply.log 2>&1; then
        echo "$m APPLY-FAILED" >> $SP/mutants/summary.txt; continue
    fi
    timeout 900 ./test.sh new $SP/mutants/$m.xml > $SP/mutants/$m.log 2>&1
    st=$?
    failed=$(grep -oE "FAIL \[[^]]*\] \([0-9]+/[0-9]+\) common-meta ddl::tests::batch_drop_logical_tables::[a-z_]+" $SP/mutants/$m.log | sed 's/.*:://' | sort -u | tr '\n' ' ')
    summ=$(grep -E "Summary" $SP/mutants/$m.log | tail -1 | sed 's/^ *//')
    build=$(grep -q "failed to build" $SP/mutants/$m.log && echo BUILD-FAILED || echo built)
    echo "$m exit=$st $build | $summ | failed: $failed" >> $SP/mutants/summary.txt
done
restore && echo "RESTORED" >> $SP/mutants/summary.txt
