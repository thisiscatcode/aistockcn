from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / "apps" / "web-fei" / "app" / "fei-selection" / "shareholder-ranking.ts"
TYPESCRIPT_PATH = ROOT / "apps" / "web-fei" / "node_modules" / "typescript"


def test_fei_shareholder_ranking_helper_matches_peak_decline_rule() -> None:
    if not HELPER_PATH.exists() or not TYPESCRIPT_PATH.exists():
        pytest.skip("apps/web-fei is a local deployment fork and is not available in this checkout")

    script = textwrap.dedent(
        r"""
        const fs = require("fs");
        const vm = require("vm");
        const ts = require("./apps/web-fei/node_modules/typescript");

        const source = fs.readFileSync("apps/web-fei/app/fei-selection/shareholder-ranking.ts", "utf8");
        const output = ts.transpileModule(source, {
          compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
        }).outputText;
        const module = { exports: {} };
        vm.runInNewContext(output, { module, exports: module.exports, require, console });

        const {
          isShareholderPeakDeclineCandidate,
          shareholderPeakDeclineSort,
        } = module.exports;
        const assert = require("assert");

        const base = {
          code: "000001",
          exchange: "sz",
          trade_date: "2026-06-15T00:00:00",
          first_trade_date: "2025-06-14T00:00:00",
          shareholder_report_date: "2026-05-29",
          shareholder_total_num: 130000,
          shareholder_peak_total_num: 146000,
          shareholder_total_num_from_peak_change: -16000,
          shareholder_total_num_from_peak_change_pct: -10.9589,
        };

        assert.equal(isShareholderPeakDeclineCandidate(base), true);
        assert.equal(isShareholderPeakDeclineCandidate({
          ...base,
          shareholder_total_num: 139000,
          shareholder_total_num_from_peak_change_pct: -4.79,
        }), false);
        assert.equal(isShareholderPeakDeclineCandidate({
          ...base,
          shareholder_peak_total_num: null,
          shareholder_total_num_from_peak_change_pct: null,
        }), false);
        assert.equal(isShareholderPeakDeclineCandidate({
          ...base,
          shareholder_report_date: "2026-04-01",
        }), false);
        assert.equal(isShareholderPeakDeclineCandidate({
          ...base,
          first_trade_date: "2026-01-01T00:00:00",
        }), false);

        const sorted = [
          { ...base, code: "000003", shareholder_total_num: 130000, shareholder_total_num_from_peak_change_pct: -12 },
          { ...base, code: "000001", shareholder_total_num: 150000, shareholder_total_num_from_peak_change_pct: -20 },
          { ...base, code: "000002", shareholder_total_num: 100000, shareholder_total_num_from_peak_change_pct: -12 },
        ].sort(shareholderPeakDeclineSort);
        assert.deepEqual(sorted.map((row) => row.code), ["000001", "000002", "000003"]);
        """
    )
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)
