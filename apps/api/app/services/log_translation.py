from __future__ import annotations

import re


LOG_TRANSLATIONS: tuple[tuple[str, str], ...] = (
    (r"^\u8bf7\u6c42\u5931\u8d25\uff0c([0-9.]+) \u79d2\u540e\u91cd\u8bd5 \((\d+)/(\d+)\): (.+)$", r"Request failed, retrying in \1s (\2/\3): \4"),
    (r"^Baostock \u4f1a\u8bdd\u5df2\u5931\u6548\uff0c\u6b63\u5728\u81ea\u52a8\u91cd\u65b0\u767b\u5f55\.\.\.$", r"Baostock session expired, re-authenticating..."),
    (r"^Baostock \u767b\u5f55\u5931\u8d25: (.+)$", r"Baostock login failed: \1"),
    (r"^AkShare \u4ea4\u6613\u65e5\u5386\u5931\u8d25\uff0c\u56de\u9000 BaoStock: (.+)$", r"AkShare trading calendar failed, falling back to BaoStock: \1"),
    (r"^\u672a\u627e\u5230 (.+) \u4e4b\u524d\u7684\u6700\u8fd1\u4ea4\u6613\u65e5$", r"No latest trading day found before \1"),
    (r"^\u672a\u627e\u5230 (.+) \u4e4b\u524d\u7684\u4ea4\u6613\u65e5$", r"No trading day found before \1"),
    (r"^\u6b63\u5728\u901a\u8fc7 Baostock \u83b7\u53d6\u5168\u5e02\u573a A \u80a1\u540d\u5355\uff0c\u4ea4\u6613\u65e5: (.+)\.\.\.$", r"Fetching full A-share universe from Baostock, trade date: \1..."),
    (r"^(.+) \u8fd4\u56de\u7a7a\u80a1\u7968\u5217\u8868\uff0c\u56de\u9000\u5230\u66f4\u65e9\u4ea4\u6613\u65e5\u7ee7\u7eed\u5c1d\u8bd5\u3002$", r"\1 returned an empty stock list, falling back to an earlier trade date."),
    (r"^(.+) \u8fc7\u6ee4\u540e\u65e0\u6709\u6548 A \u80a1\u5217\u8868\uff0c\u56de\u9000\u5230\u66f4\u65e9\u4ea4\u6613\u65e5\u7ee7\u7eed\u5c1d\u8bd5\u3002$", r"\1 returned no investable A-shares after filtering, falling back to an earlier trade date."),
    (r"^\u6b63\u5728\u901a\u8fc7 Baostock \u83b7\u53d6\u6caa\u6df1300\u6210\u5206\u80a1\u540d\u5355\.\.\.$", r"Fetching CSI 300 constituents from Baostock..."),
    (r"^\u884c\u4e1a\u8865\u5168\u5df2\u542f\u7528\uff1a\u5f53\u524d\u5df2\u77e5\u884c\u4e1a (\d+)/(\d+)\uff0c\u5f85\u8865 (\d+)\u3002$", r"Industry enrichment enabled: \1/\2 industries already known, \3 to fill."),
    (r"^\[stock_list (\d+)/(\d+)\] \u6b63\u5728\u901a\u8fc7 Baostock \u8865\u5145\u884c\u4e1a\u4fe1\u606f: (\d+)$", r"[stock_list \1/\2] Filling industry metadata from Baostock: \3"),
    (r"^\u8865\u5145 (\d+) \u884c\u4e1a\u4fe1\u606f\u5931\u8d25: (.+)$", r"Failed to fill industry metadata for \1: \2"),
    (r"^\u884c\u4e1a\u8865\u5168\u5b8c\u6210\uff1a\u5df2\u77e5\u884c\u4e1a (\d+)/(\d+)\uff0c\u4ecd\u7f3a\u5931 (\d+)\u3002$", r"Industry enrichment finished: \1/\2 industries known, \3 still missing."),
    (r"^\u884c\u4e1a\u8865\u5168\u5df2\u8df3\u8fc7\uff1a\u5f53\u524d\u5df2\u77e5\u884c\u4e1a (\d+)/(\d+)\uff0c\u7f3a\u5931 (\d+)\u3002\u5982\u9700\u6062\u590d industry \u7279\u5f81\uff0c\u8bf7\u542f\u7528 --include-industry\u3002$", r"Industry enrichment skipped: \1/\2 industries known, \3 missing. Enable --include-industry to restore the industry feature."),
    (r"^\u6d3b\u8dc3\u80a1\u7968\u6c60\u5df2\u4fdd\u5b58\u81f3 (.+)\uff0c\u5171 (\d+) \u53ea\u80a1\u7968\u3002$", r"Active universe saved to \1, \2 stocks."),
    (r"^\u4e3b\u6ce8\u518c\u8868\u5df2\u4fdd\u5b58\u81f3 (.+)\uff0c\u5171 (\d+) \u53ea\u80a1\u7968\u3002$", r"Master registry saved to \1, \2 stocks."),
    (r"^\u80a1\u7968\u6c60\u540c\u6b65\u7ed3\u679c: \u65b0\u589e (\d+)\uff0c\u6062\u590d (\d+)\uff0c\u505c\u7528 (\d+)$", r"Universe sync result: added \1, reactivated \2, deactivated \3"),
    (r"^\u5b50\u96c6\u80a1\u7968\u5217\u8868\u5df2\u4fdd\u5b58\u81f3 (.+)\uff0c\u5171 (\d+) \u53ea\u80a1\u7968\u3002$", r"Subset stock list saved to \1, \2 stocks."),
    (r"^\u5f53\u524d\u4efb\u52a1\u4e3a\u5b50\u96c6/\u6d4b\u8bd5\u6a21\u5f0f\uff0c\u672a\u8986\u76d6 (.+) \u548c (.+)\u3002$", r"Scoped run active; \1 and \2 were not overwritten."),
    (r"^\u672c\u6b21\u4efb\u52a1\u80a1\u7968\u6570\u91cf: (\d+)\uff0c\u80a1\u7968\u6c60: (.+)$", r"Stocks in this run: \1, universe: \2"),
    (r"^\u5f00\u59cb\u4e0b\u8f7d\u524d\u590d\u6743\u65e5 K \u7ebf\u6570\u636e\.\.\.$", r"Starting adjusted daily K-line download..."),
    (r"^\u5f00\u59cb\u4e0b\u8f7d\u6bcf\u65e5\u4f30\u503c\u6570\u636e\.\.\.$", r"Starting daily valuation download..."),
    (r"^\[(\d+)/(\d+)\] \u6b63\u5728\u901a\u8fc7 Baostock \u4e0b\u8f7d: (\d+)$", r"[\1/\2] Downloading from Baostock: \3"),
    (r"^\u4e0b\u8f7d (\d+) \u5931\u8d25: (.+)$", r"Download failed for \1: \2"),
    (r"^\u5199\u5165 (\d+) \u65e5 K \u7ebf\u5931\u8d25: (.+)$", r"Failed to write daily K-line for \1: \2"),
    (r"^(\d{6}) \u4f30\u503c\u8865\u5145\u63d0\u9192: (.+)$", r"\1 valuation supplement note: \2"),
    (r"^\u5199\u5165 (\d+) \u4f30\u503c\u6570\u636e\u5931\u8d25: (.+)$", r"Failed to write valuation data for \1: \2"),
    (r"^\u524d\u590d\u6743\u65e5 K \u7ebf\u4e0b\u8f7d\u5b8c\u6210\uff0c\u6210\u529f (\d+)/(\d+)\u3002$", r"Adjusted daily K-line download completed, succeeded \1/\2."),
    (r"^\u6bcf\u65e5\u4f30\u503c\u6570\u636e\u4e0b\u8f7d\u5b8c\u6210\uff0c\u6210\u529f (\d+)/(\d+)\u3002$", r"Daily valuation download completed, succeeded \1/\2."),
    (r"^\u5931\u8d25\u660e\u7ec6\u5df2\u5199\u5165 (.+)$", r"Failure details written to \1"),
    (r"^\u5168\u90e8\u4efb\u52a1\u5b8c\u6210\u3002$", r"All tasks completed."),
    (r"^\u5168\u5e02\u573a\u80a1\u7968\u6570: (\d+)$", r"Full-market stock count: \1"),
    (r"^\u5df2\u5b8c\u6210: (\d+)$", r"Completed: \1"),
    (r"^\u72b6\u6001\u6587\u4ef6: (.+)$", r"State file: \1"),
    (r"^\u76ee\u6807\u4ea4\u6613\u65e5: (.+)$", r"Target trading day: \1"),
    (r"^\u6162\u8b8a\u8cc7\u6599\u80a1\u7968\u6578: (\d+)$", r"Slow-reference stock count: \1"),
    (r"^\u6162\u53d8\u8d44\u6599\u80a1\u7968\u6570: (\d+)$", r"Slow-reference stock count: \1"),
    (r"^\[reference (\d+)/(\d+)\] \u5237\u65b0\u6162\u53d8\u8d44\u6599: (\d+)$", r"[reference \1/\2] Refreshing slow reference data: \3"),
    (r"^\u5f00\u59cb\u7b2c (\d+)/(\d+) \u8f6e\uff0c\u5f85\u5904\u7406\u80a1\u7968\u6570: (\d+)$", r"Starting pass \1/\2, pending stocks: \3"),
    (r"^\[pass (\d+) (\d+)/(\d+)\] \u4e0b\u8f7d (\d+)\uff0c\u5c1d\u8bd5\u6b21\u6570 (\d+)/(\d+)$", r"[pass \1 \2/\3] Downloading \4, attempt \5/\6"),
    (r"^\u4e0b\u8f7d (\d+)\uff0c\u5c1d\u8bd5\u6b21\u6570 (\d+)/(\d+)$", r"Downloading \1, attempt \2/\3"),
    (r"^\u8fbe\u5230\u91cd\u65b0\u767b\u5f55\u9608\u503c\uff0c\u91cd\u8fde Baostock\.\.\.$", r"Reached re-login threshold, reconnecting to Baostock..."),
    (r"^(\d{6}) \u5b8c\u6210\uff0c\u63d0\u9192: (.+)$", r"\1 completed, note: \2"),
    (r"^(\d{6}) \u5b8c\u6210$", r"\1 completed"),
    (r"^(\d{6}) \u5931\u8d25: (.+)$", r"\1 failed: \2"),
    (r"^\u7b2c (\d+) \u8f6e\u7ed3\u675f\uff0c\u7d2f\u8ba1\u5b8c\u6210 (\d+)/(\d+)\uff0c\u5269\u4f59\u5f85\u91cd\u8bd5 (\d+)$", r"Pass \1 finished, completed \2/\3, remaining for retry: \4"),
    (r"^\u6682\u505c ([0-9.]+) \u5206\u949f\u540e\u8fdb\u5165\u4e0b\u4e00\u8f6e\.\.\.$", r"Pausing \1 minutes before the next pass..."),
    (r"^stock_list\.parquet \u7f3a\u5c11 exchange \u5217\uff0c\u8bf7\u5148\u91cd\u65b0\u8fd0\u884c download_data\.py \u5237\u65b0\u80a1\u7968\u5217\u8868\u3002$", r"stock_list.parquet is missing the exchange column. Re-run download_data.py to refresh the stock list."),
    (r"^\u6ca1\u6709\u53ef\u7528\u7684 K \u7ebf/\u4f30\u503c parquet \u53ef\u5408\u5e76\u3002$", r"No K-line / valuation parquet files are available to merge."),
    (r"^\u5df2\u5904\u7406 (\d+)/(\d+) \u53ea\u80a1\u7968\uff0c\u5f53\u524d\u7d2f\u8ba1 (\d+) \u53ea\u8fdb\u5165\u8bad\u7ec3\u96c6\uff0c(\d+) \u884c\u3002$", r"Processed \1/\2 stocks, \3 included in training so far, \4 rows."),
    (r"^\u6ca1\u6709\u751f\u6210\u4efb\u4f55\u53ef\u7528\u8bad\u7ec3\u6837\u672c\u3002$", r"No usable training samples were generated."),
    (r"^\u539f\u59cb\u9762\u677f\u6570\u636e\u7ef4\u5ea6: \((.+)\)$", r"Raw panel shape: (\1)"),
    (r"^\u7279\u5f81\u5de5\u7a0b\u5b8c\u6210\uff0c\u53ef\u8bad\u7ec3\u6570\u636e\u7ef4\u5ea6: \((.+)\)$", r"Feature engineering completed, trainable shape: (\1)"),
    (r"^\u8f93\u51fa\u6587\u4ef6: (.+)$", r"Output file: \1"),
    (r"^\u7279\u5f81\u5143\u6570\u636e\u6587\u4ef6: (.+)$", r"Feature metadata file: \1"),
    (r"^\u5df2\u5904\u7406 (\d+)/(\d+) \u53ea\u80a1\u7968\.\.\.$", r"Processed \1/\2 stocks..."),
    (r"^\u6ca1\u6709\u751f\u6210\u4efb\u4f55\u53ef\u7528\u7684\u63a8\u7406\u7279\u5f81\u3002$", r"No usable inference features were generated."),
    (r"^\u63a8\u7406\u7279\u5f81\u5b8c\u6210\uff0c\u6570\u636e\u7ef4\u5ea6: (.+)$", r"Inference features completed, shape: \1"),
    (r"^\u52a0\u8f7d\u8bad\u7ec3\u6570\u636e: (.+)$", r"Loading training data: \1"),
    (r"^\u8bad\u7ec3\u5217\u6570: (\d+)\uff0c\u6a21\u578b\u7279\u5f81\u6570: (\d+)\uff0c\u7c7b\u522b\u7279\u5f81: (\d+)$", r"Training columns: \1, model features: \2, categorical features: \3"),
    (r"^\u52a0\u8f7d\u6253\u5206\u6570\u636e: (.+)$", r"Loading scoring data: \1"),
    (r"^\u8bad\u7ec3\u96c6\u5f62\u72b6: (.+)\uff0c\u6253\u5206\u96c6\u5f62\u72b6: (.+)$", r"Training shape: \1, scoring shape: \2"),
    (r"^\u8bad\u7ec3/\u9a8c\u8bc1\u5207\u5206\u5b8c\u6210: train=(.+)\uff0cvalid=(.+)$", r"Train/validation split completed: train=\1, valid=\2"),
    (r"^\u6784\u5efa\u8bad\u7ec3\u4e0e\u9a8c\u8bc1\u7279\u5f81\u77e9\u9635\.\.\.$", r"Building training and validation feature matrices..."),
    (r"^\u7279\u5f81\u77e9\u9635\u5b8c\u6210: X_train=(.+)\uff0cX_valid=(.+)$", r"Feature matrices completed: X_train=\1, X_valid=\2"),
    (r"^\u5f00\u59cb\u8bad\u7ec3 LightGBM\.\.\.$", r"Starting LightGBM training..."),
    (r"^\u8bad\u7ec3\u5b8c\u6210\uff0c\u5f00\u59cb\u5199\u51fa\u6a21\u578b\u4e0e\u6307\u6807\.\.\.$", r"Training completed, writing model and metrics..."),
    (r"^\u6784\u5efa\u63a8\u7406\u7279\u5f81\u77e9\u9635\u5e76\u751f\u6210\u5206\u6570\.\.\.$", r"Building inference feature matrix and generating scores..."),
    (r"^\u8bad\u7ec3\u5b8c\u6210\u3002$", r"Training completed."),
    (r"^\u6a21\u578b\u76ee\u5f55: (.+)$", r"Model directory: \1"),
    (r"^\u4ea4\u6613\u65e5\u6570\u91cf\u4e0d\u8db3\uff0c\u65e0\u6cd5\u542f\u52a8 walk-forward \u56de\u6d4b\u3002$", r"Not enough trading days to start walk-forward backtest."),
    (r"^\u6ca1\u6709\u53ef\u7528\u4e8e\u56de\u6d4b\u7684\u8c03\u4ed3\u65e5\u671f\u3002$", r"No rebalance dates are available for backtesting."),
    (r"^\u56de\u6d4b\u6ca1\u6709\u751f\u6210\u4efb\u4f55\u9884\u6d4b\u7ed3\u679c\u3002$", r"Backtest produced no predictions."),
    (r"^\u4e25\u683c OOS \u56de\u6d4b\u5b8c\u6210\u3002$", r"Strict OOS backtest completed."),
    (r"^\u5831\u55ae\u50f9\u683c\u4e0d\u5728\u6f32\u8dcc\u505c\u5340\u9593$", r"Order price is outside the daily price limit range."),
    (r"^\u62a5\u5355\u4ef7\u683c\u4e0d\u5728\u6da8\u8dcc\u505c\u533a\u95f4$", r"Order price is outside the daily price limit range."),
)


def translate_log_line(line: str) -> str:
    text = line.rstrip("\n")
    for pattern, replacement in LOG_TRANSLATIONS:
        translated = re.sub(pattern, replacement, text)
        if translated != text:
            return translated
    return text


def translate_log_lines(lines: list[str]) -> list[str]:
    return [translate_log_line(line) for line in lines]
