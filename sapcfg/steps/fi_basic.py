"""Built-in configuration steps for the example Template (FICO basics).

Design doc §4.3: GUI control mechanics live here (versioned "skill"), the Template
holds only business intent. Each step kind declares:

  * transaction + semantic screen fields (id/label/kind/control-hints),
  * how save maps into the configuration store (mock) -- for the real channel this is
    where per-version control paths are recorded,
  * which table the planner reads to decide CREATE/UPDATE/SKIP/CONFLICT,
  * verification mapping (param key -> stored column).

Handler `apply()` drives the adapter through the concrete actions of that step.
"""
from __future__ import annotations

from typing import Any, Optional

from ..model import ConfigItem

# --------------------------------------------------------------------------
# screen catalog (mock driver consumes this to emulate GUI behaviour)
# --------------------------------------------------------------------------
SCREENS: list[dict] = [
    dict(
        tcode="OB13", kind="chart_of_accounts",
        title="Edit Chart of Accounts List",
        key_field="code", key_label="Chart of accounts",
        fields=[
            dict(id="code", label="Chart of accounts", kind="text", key=True),
            dict(id="name", label="Name", kind="text"),
        ],
        columns=dict(code="code", name="name"),
        save_table="coa", save_key="code",
        read_table="coa", read_key="code",
        validators=[],
        success_message="Chart of accounts was saved",
    ),
    dict(
        tcode="OB29", kind="fiscal_year_variant",
        title="Maintain Fiscal Year Variant",
        key_field="code", key_label="Fiscal year variant",
        fields=[
            dict(id="code", label="Fiscal year variant", kind="text", key=True),
            dict(id="name", label="Description", kind="text"),
            dict(id="n_periods", label="Number of posting periods", kind="text"),
        ],
        columns=dict(code="code", name="name", n_periods="n_periods"),
        save_table="fiscal_variant", save_key="code",
        read_table="fiscal_variant", read_key="code",
        validators=[],
        success_message="Fiscal year variant was saved",
    ),
    dict(
        tcode="OBY6", kind="company_code_global_params",
        title="Global Parameters for Company Code",
        key_field="company_code", key_label="Company code",
        fields=[
            dict(id="company_code", label="Company code", kind="text", key=True),
            dict(id="company_name", label="Company name", kind="text"),
            dict(id="currency", label="Currency key", kind="text"),
            dict(id="chart_of_accounts", label="Chart of accounts",
                 kind="dropdown", options_table="coa"),
            dict(id="fiscal_year_variant", label="Fiscal year variant",
                 kind="dropdown", options_table="fiscal_variant"),
            dict(id="country", label="Country key", kind="text"),
            dict(id="city", label="City", kind="text"),
            dict(id="language", label="Language key", kind="text"),
        ],
        columns=dict(company_code="company_code", company_name="company_name",
                     currency="currency", chart_of_accounts="chart_of_accounts",
                     fiscal_year_variant="fiscal_year_variant", country="country",
                     city="city", language="language"),
        save_table="company_code", save_key="company_code",
        read_table="company_code", read_key="company_code",
        validators=[
            dict(type="exists_in", field="chart_of_accounts", table="coa",
                 msg="Chart of accounts"),
            dict(type="exists_in", field="fiscal_year_variant",
                 table="fiscal_variant", msg="Fiscal year variant"),
        ],
        success_message="Company code was saved",
    ),
    dict(
        tcode="OX02", kind="assign_companycode_company",
        title="Assign Company Code to Company",
        key_field="company_code", key_label="Company code",
        fields=[
            dict(id="company_code", label="Company code", kind="text", key=True),
            dict(id="company", label="Company", kind="dropdown",
                 options_table="company"),
        ],
        columns=dict(company_code="company_code", company="company"),
        save_table="cc_company_assign", save_key="company_code",
        read_table="cc_company_assign", read_key="company_code",
        validators=[dict(type="member_of", field="company", table="company",
                         msg="Company")],
        success_message="Assignment saved",
    ),
    dict(
        tcode="OX10", kind="plant_create",
        title="Define Plant",
        key_field="plant", key_label="Plant",
        fields=[
            dict(id="plant", label="Plant", kind="text", key=True),
            dict(id="company_code", label="Company code", kind="dropdown",
                 options_table="company_code"),
            dict(id="name_1", label="Name 1", kind="text"),
        ],
        columns=dict(plant="plant", company_code="company_code", name_1="name_1"),
        save_table="plant", save_key="plant",
        read_table="plant", read_key="plant",
        validators=[dict(type="exists_in", field="company_code",
                         table="company_code", msg="Company code")],
        success_message="Plant was saved",
    ),
]

SCREENS_BY_TCODE = {s["tcode"]: s for s in SCREENS}

# planner: which store table/key represent "does this config exist?"
HANDLER_TABLES: dict[str, dict[str, str]] = {
    "chart_of_accounts": dict(table="coa", key="code"),
    "fiscal_year_variant": dict(table="fiscal_variant", key="code"),
    "company_code_global_params": dict(table="company_code", key="company_code"),
    "assign_companycode_company": dict(table="cc_company_assign", key="company_code"),
    "plant_create": dict(table="plant", key="plant"),
}


# --------------------------------------------------------------------------
# step handlers (per config step kind)
# --------------------------------------------------------------------------
class StepHandler:
    kind: str = ""
    tcode: str = ""
    verify_columns: dict[str, str] = {}   # param key -> stored column

    def screen(self) -> dict:
        return SCREENS_BY_TCODE[self.tcode]

    # actions are described declaratively; the generic executor runs them.
    def actions(self, p: dict[str, Any]) -> list[dict]:
        """Ordered screen actions: ('fill'|'dropdown'|'key', field_id, value)."""
        out = [dict(op="key", field=self.screen()["key_field"],
                    value=p[self.screen()["key_field"]])]
        for f in self.screen()["fields"]:
            fid = f["id"]
            if fid == self.screen()["key_field"] or fid not in p:
                continue
            op = "dropdown" if f["kind"] == "dropdown" else "fill"
            out.append(dict(op=op, field=fid, value=str(p[fid])))
        return out

    def apply(self, adapter, item: ConfigItem, step_log) -> dict:
        """Drive the adapter through this step. Returns status message."""
        p = item.resolved_params
        screen = adapter.start_transaction(self.tcode)
        step_log("screen", adapter.capture_screen())
        for a in self.actions(p):
            if a["op"] == "key":
                adapter.fill_key(a["field"], a["value"])
            elif a["op"] == "dropdown":
                adapter.select_dropdown(a["field"], a["value"])
            else:
                adapter.fill(a["field"], a["value"])
            step_log("action", dict(op=a["op"], field=a["field"], value=a["value"]))
        step_log("screen", adapter.capture_screen())
        msg = adapter.save()
        step_log("message", dict(text=msg, cls=adapter.status_class()))
        step_log("screen", adapter.capture_screen())
        return dict(message=msg)


class ChartOfAccounts(StepHandler):
    kind, tcode = "chart_of_accounts", "OB13"
    verify_columns = dict(code="code", name="name")


class FiscalYearVariant(StepHandler):
    kind, tcode = "fiscal_year_variant", "OB29"
    verify_columns = dict(code="code", name="name", n_periods="n_periods")


class CompanyCodeGlobalParams(StepHandler):
    kind, tcode = "company_code_global_params", "OBY6"
    verify_columns = dict(company_code="company_code", company_name="company_name",
                          currency="currency", chart_of_accounts="chart_of_accounts",
                          fiscal_year_variant="fiscal_year_variant", country="country",
                          city="city", language="language")


class AssignCompanyCodeCompany(StepHandler):
    kind, tcode = "assign_companycode_company", "OX02"
    verify_columns = dict(company_code="company_code", company="company")


class PlantCreate(StepHandler):
    kind, tcode = "plant_create", "OX10"
    verify_columns = dict(plant="plant", company_code="company_code", name_1="name_1")


HANDLERS: dict[str, StepHandler] = {h.kind: h for h in (
    ChartOfAccounts(), FiscalYearVariant(), CompanyCodeGlobalParams(),
    AssignCompanyCodeCompany(), PlantCreate())}


def get_handler(kind: str) -> Optional[StepHandler]:
    return HANDLERS.get(kind)
