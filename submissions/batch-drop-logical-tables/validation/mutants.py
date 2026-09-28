# Copyright 2023 Greptime Team
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Applies one named mutant to the reference solution in the working tree."""
import sys

P = "src/common/meta/src/ddl/drop_logical_tables.rs"
M = "src/common/meta/src/ddl_manager.rs"


def edit(path, old, new, count=1):
    s = open(path).read()
    assert s.count(old) == count, (path, old[:80], s.count(old))
    open(path, "w").write(s.replace(old, new))


def m01_no_parent_check():
    edit(P, """                Some(physical_table_id) => ensure!(
                    physical_table_id == current,
                    error::DropLogicalTablesInvalidArgumentsSnafu {
                        err_msg: "All the tables should have the same physical table id",
                    }
                ),""", """                Some(_) => {}""")
    edit(P, """        ensure!(
            self.data.physical_table_id == Some(physical_table_id),""", """        ensure!(
            self.data.physical_table_id.is_some() || physical_table_id == 0,""")


def m02_missing_always_skipped():
    edit(P, """                ensure!(
                    task.drop_if_exists,
                    error::TableNotFoundSnafu {
                        table_name: task.table_ref().to_string(),
                    }
                );
                continue;""", """                continue;""")


def m03_non_logical_skipped():
    edit(P, """    let mut physical_table_id = None;
        for (task, table_route) in tables.iter().zip(table_routes) {""", """    let mut physical_table_id = None;
        let mut kept = Vec::new();
        for (task, table_route) in tables.iter().zip(table_routes) {""", count=0) if False else None
    edit(P, """            let TableRouteValue::Logical(table_route) = table_route else {
                return error::DropLogicalTablesInvalidArgumentsSnafu {
                    err_msg: format!("table {} is not a logical table", task.table_ref()),
                }
                .fail();
            };""", """            let TableRouteValue::Logical(table_route) = table_route else {
                continue;
            };""")
    # Drops the non-logical targets from the batch instead of rejecting it.
    edit(P, """        let physical_table_id = physical_table_id.unwrap();""", """        let physical_table_id = physical_table_id.unwrap();
        let logical_ids = table_routes_logical_ids(&self.context, &table_ids).await?;
        let tables = tables
            .into_iter()
            .filter(|task| logical_ids.contains(&task.table_id))
            .collect::<Vec<_>>();""")
    s = open(P).read()
    s += """
async fn table_routes_logical_ids(context: &DdlContext, table_ids: &[TableId]) -> Result<HashSet<TableId>> {
    let routes = context
        .table_metadata_manager
        .table_route_manager()
        .table_route_storage()
        .batch_get(table_ids)
        .await?;
    Ok(table_ids
        .iter()
        .zip(routes)
        .filter(|(_, route)| matches!(route, Some(TableRouteValue::Logical(_))))
        .map(|(id, _)| *id)
        .collect())
}
"""
    open(P, "w").write(s)
    # A physical first target no longer locks as the physical table.
    edit(P, """        ensure!(
            self.data.physical_table_id == Some(physical_table_id),""", """        ensure!(
            self.data.physical_table_id.is_some(),""")


def m04_no_loader():
    edit(M, """            DropTableProcedure,
            DropLogicalTablesProcedure,
            DropFlowProcedure,""", """            DropTableProcedure,
            DropFlowProcedure,""")


def m05_no_cache_invalidation():
    edit(P, """        self.context
            .cache_invalidator
            .invalidate(&ctx, &cache_idents)
            .await?;""", """        let _ = (&ctx, &cache_idents);""")


def m06_per_table_region_registration():
    edit(P, """        if !self.dropping_regions.is_empty() {
            return Ok(());
        }

        let dropping_regions""", """        let dropping_regions""")
    edit(P, """        self.dropping_regions = dropping_region_guards;
        Ok(())""", """        self.dropping_regions.extend(dropping_region_guards);
        Ok(())""")
    edit(P, """    pub(crate) async fn on_delete_metadata(&mut self) -> Result<Status> {
        self.register_dropping_regions()?;""", """    pub(crate) async fn on_delete_metadata(&mut self) -> Result<Status> {
        for _ in 0..self.data.tables.len() {
            self.register_dropping_regions()?;
        }""")


def m07_handler_loops_single_drops():
    edit(M, """        let procedure =
            DropLogicalTablesProcedure::new(drop_table_tasks, physical_table_id, context);

        let procedure_with_id =
            ProcedureWithId::with_random_id(Box::new(procedure)).with_context(procedure_context);

        self.execute_procedure_and_wait(procedure_with_id).await""", """        let _ = (physical_table_id, context);
        let mut last = None;
        let mut seen = std::collections::HashSet::new();
        for task in drop_table_tasks {
            if !seen.insert(task.table_id) {
                continue;
            }
            last = Some(
                self.submit_drop_table_task(task, procedure_context.clone())
                    .await?,
            );
        }
        Ok(last.unwrap())""")


def m08_no_persistence():
    edit(P, "Ok(Status::executing(true))", "Ok(Status::executing(false))", count=4)


def m09_drops_physical_regions():
    edit(P, """            let executor =
                DropTableExecutor::new(task.table_name(), task.table_id, task.drop_if_exists);""", """            let executor = DropTableExecutor::new(
                task.table_name(),
                region_routes[0].region.id.table_id(),
                task.drop_if_exists,
            );""")


def m10_only_first_target_regions():
    edit(P, """        let drop_regions = self.data.tables.iter().map(|task| {""", """        let drop_regions = self.data.tables.iter().take(1).map(|task| {""")


def m11_mutate_before_validate():
    edit(P, """    pub(crate) async fn on_prepare(&mut self) -> Result<Status> {
        let table_name_keys = self""", """    pub(crate) async fn on_prepare(&mut self) -> Result<Status> {
        let existing = self
            .context
            .table_metadata_manager
            .table_name_manager()
            .batch_get(
                self.data
                    .tasks
                    .iter()
                    .map(|task| TableNameKey::new(&task.catalog, &task.schema, &task.table))
                    .collect(),
            )
            .await?;
        let mut deleted = Vec::new();
        for (task, value) in self.data.tasks.iter().zip(existing) {
            if value.is_some() && deleted.iter().all(|(id, _)| *id != task.table_id) {
                deleted.push((task.table_id, task.table_name()));
            }
        }
        if let Some(physical_table_id) = self.data.physical_table_id {
            self.context
                .table_metadata_manager
                .delete_logical_tables_metadata(physical_table_id, &deleted)
                .await?;
        }
        let table_name_keys = self""")


def m12_no_dedup():
    edit(P, """            if dropping_table_ids.insert(task.table_id) {
                tables.push(task.clone());
            }""", """            dropping_table_ids.insert(task.table_id);
            tables.push(task.clone());""")


MUTANTS = {name: fn for name, fn in globals().items() if name.startswith("m") and name[1:3].isdigit()}

if __name__ == "__main__":
    if sys.argv[1] == "list":
        print("\n".join(sorted(MUTANTS)))
    else:
        MUTANTS[sys.argv[1]]()
