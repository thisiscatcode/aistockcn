from __future__ import annotations

import re


LOG_TRANSLATIONS: tuple[tuple[str, str], ...] = (
    (r"^请求失败，([0-9.]+) 秒后重试 \((\d+)/(\d+)\): (.+)$", r"Request failed, retrying in \1s (\2/\3): \4"),
    (r"^Baostock 会话已失效，正在自动重新登录\.\.\.$", r"Baostock session expired, re-authenticating..."),
    (r"^Baostock 登录失败: (.+)$", r"Baostock login failed: \1"),
    (r"^AkShare 交易日历失败，回退 BaoStock: (.+)$", r"AkShare trading calendar failed, falling back to BaoStock: \1"),
    (r"^未找到 (.+) 之前的最近交易日$", r"No latest trading day found before \1"),
    (r"^未找到 (.+) 之前的交易日$", r"No trading day found before \1"),
    (r"^正在通过 Baostock 获取全市场 A 股名单，交易日: (.+)\.\.\.$", r"Fetching full A-share universe from Baostock, trade date: \1..."),
    (r"^(.+) 返回空股票列表，回退到更早交易日继续尝试。$", r"\1 returned an empty stock list, falling back to an earlier trade date."),
    (r"^(.+) 过滤后无有效 A 股列表，回退到更早交易日继续尝试。$", r"\1 returned no investable A-shares after filtering, falling back to an earlier trade date."),
    (r"^正在通过 Baostock 获取沪深300成分股名单\.\.\.$", r"Fetching CSI 300 constituents from Baostock..."),
    (r"^行业补全已启用：当前已知行业 (\d+)/(\d+)，待补 (\d+)。$", r"Industry enrichment enabled: \1/\2 industries already known, \3 to fill."),
    (r"^\[stock_list (\d+)/(\d+)\] 正在通过 Baostock 补充行业信息: (\d+)$", r"[stock_list \1/\2] Filling industry metadata from Baostock: \3"),
    (r"^补充 (\d+) 行业信息失败: (.+)$", r"Failed to fill industry metadata for \1: \2"),
    (r"^行业补全完成：已知行业 (\d+)/(\d+)，仍缺失 (\d+)。$", r"Industry enrichment finished: \1/\2 industries known, \3 still missing."),
    (r"^行业补全已跳过：当前已知行业 (\d+)/(\d+)，缺失 (\d+)。如需恢复 industry 特征，请启用 --include-industry。$", r"Industry enrichment skipped: \1/\2 industries known, \3 missing. Enable --include-industry to restore the industry feature."),
    (r"^活跃股票池已保存至 (.+)，共 (\d+) 只股票。$", r"Active universe saved to \1, \2 stocks."),
    (r"^主注册表已保存至 (.+)，共 (\d+) 只股票。$", r"Master registry saved to \1, \2 stocks."),
    (r"^股票池同步结果: 新增 (\d+)，恢复 (\d+)，停用 (\d+)$", r"Universe sync result: added \1, reactivated \2, deactivated \3"),
    (r"^子集股票列表已保存至 (.+)，共 (\d+) 只股票。$", r"Subset stock list saved to \1, \2 stocks."),
    (r"^当前任务为子集/测试模式，未覆盖 (.+) 和 (.+)。$", r"Subset/test mode is active; \1 and \2 were not overwritten."),
    (r"^本次任务股票数量: (\d+)，股票池: (.+)$", r"Stocks in this run: \1, universe: \2"),
    (r"^开始下载前复权日 K 线数据\.\.\.$", r"Starting adjusted daily K-line download..."),
    (r"^开始下载每日估值数据\.\.\.$", r"Starting daily valuation download..."),
    (r"^\[(\d+)/(\d+)\] 正在通过 Baostock 下载: (\d+)$", r"[\1/\2] Downloading from Baostock: \3"),
    (r"^下载 (\d+) 失败: (.+)$", r"Download failed for \1: \2"),
    (r"^写入 (\d+) 日 K 线失败: (.+)$", r"Failed to write daily K-line for \1: \2"),
    (r"^(\d{6}) 估值补充提醒: (.+)$", r"\1 valuation supplement note: \2"),
    (r"^写入 (\d+) 估值数据失败: (.+)$", r"Failed to write valuation data for \1: \2"),
    (r"^前复权日 K 线下载完成，成功 (\d+)/(\d+)。$", r"Adjusted daily K-line download completed, succeeded \1/\2."),
    (r"^每日估值数据下载完成，成功 (\d+)/(\d+)。$", r"Daily valuation download completed, succeeded \1/\2."),
    (r"^失败明细已写入 (.+)$", r"Failure details written to \1"),
    (r"^全部任务完成。$", r"All tasks completed."),
    (r"^全市场股票数: (\d+)$", r"Full-market stock count: \1"),
    (r"^已完成: (\d+)$", r"Completed: \1"),
    (r"^状态文件: (.+)$", r"State file: \1"),
    (r"^目标交易日: (.+)$", r"Target trading day: \1"),
    (r"^慢變資料股票數: (\d+)$", r"Slow-reference stock count: \1"),
    (r"^慢变资料股票数: (\d+)$", r"Slow-reference stock count: \1"),
    (r"^\[reference (\d+)/(\d+)\] 刷新慢变资料: (\d+)$", r"[reference \1/\2] Refreshing slow reference data: \3"),
    (r"^开始第 (\d+)/(\d+) 轮，待处理股票数: (\d+)$", r"Starting pass \1/\2, pending stocks: \3"),
    (r"^\[pass (\d+) (\d+)/(\d+)\] 下载 (\d+)，尝试次数 (\d+)/(\d+)$", r"[pass \1 \2/\3] Downloading \4, attempt \5/\6"),
    (r"^下载 (\d+)，尝试次数 (\d+)/(\d+)$", r"Downloading \1, attempt \2/\3"),
    (r"^达到重新登录阈值，重连 Baostock\.\.\.$", r"Reached re-login threshold, reconnecting to Baostock..."),
    (r"^(\d{6}) 完成，提醒: (.+)$", r"\1 completed, note: \2"),
    (r"^(\d{6}) 完成$", r"\1 completed"),
    (r"^(\d{6}) 失败: (.+)$", r"\1 failed: \2"),
    (r"^第 (\d+) 轮结束，累计完成 (\d+)/(\d+)，剩余待重试 (\d+)$", r"Pass \1 finished, completed \2/\3, remaining for retry: \4"),
    (r"^暂停 ([0-9.]+) 分钟后进入下一轮\.\.\.$", r"Pausing \1 minutes before the next pass..."),
    (r"^stock_list\.parquet 缺少 exchange 列，请先重新运行 download_data\.py 刷新股票列表。$", r"stock_list.parquet is missing the exchange column. Re-run download_data.py to refresh the stock list."),
    (r"^没有可用的 K 线/估值 parquet 可合并。$", r"No K-line / valuation parquet files are available to merge."),
    (r"^已处理 (\d+)/(\d+) 只股票，当前累计 (\d+) 只进入训练集，(\d+) 行。$", r"Processed \1/\2 stocks, \3 included in training so far, \4 rows."),
    (r"^没有生成任何可用训练样本。$", r"No usable training samples were generated."),
    (r"^原始面板数据维度: \((.+)\)$", r"Raw panel shape: (\1)"),
    (r"^特征工程完成，可训练数据维度: \((.+)\)$", r"Feature engineering completed, trainable shape: (\1)"),
    (r"^输出文件: (.+)$", r"Output file: \1"),
    (r"^特征元数据文件: (.+)$", r"Feature metadata file: \1"),
    (r"^已处理 (\d+)/(\d+) 只股票\.\.\.$", r"Processed \1/\2 stocks..."),
    (r"^没有生成任何可用的推理特征。$", r"No usable inference features were generated."),
    (r"^推理特征完成，数据维度: (.+)$", r"Inference features completed, shape: \1"),
    (r"^加载训练数据: (.+)$", r"Loading training data: \1"),
    (r"^训练列数: (\d+)，模型特征数: (\d+)，类别特征: (\d+)$", r"Training columns: \1, model features: \2, categorical features: \3"),
    (r"^加载打分数据: (.+)$", r"Loading scoring data: \1"),
    (r"^训练集形状: (.+)，打分集形状: (.+)$", r"Training shape: \1, scoring shape: \2"),
    (r"^训练/验证切分完成: train=(.+)，valid=(.+)$", r"Train/validation split completed: train=\1, valid=\2"),
    (r"^构建训练与验证特征矩阵\.\.\.$", r"Building training and validation feature matrices..."),
    (r"^特征矩阵完成: X_train=(.+)，X_valid=(.+)$", r"Feature matrices completed: X_train=\1, X_valid=\2"),
    (r"^开始训练 LightGBM\.\.\.$", r"Starting LightGBM training..."),
    (r"^训练完成，开始写出模型与指标\.\.\.$", r"Training completed, writing model and metrics..."),
    (r"^构建推理特征矩阵并生成分数\.\.\.$", r"Building inference feature matrix and generating scores..."),
    (r"^训练完成。$", r"Training completed."),
    (r"^模型目录: (.+)$", r"Model directory: \1"),
    (r"^交易日数量不足，无法启动 walk-forward 回测。$", r"Not enough trading days to start walk-forward backtest."),
    (r"^没有可用于回测的调仓日期。$", r"No rebalance dates are available for backtesting."),
    (r"^回测没有生成任何预测结果。$", r"Backtest produced no predictions."),
    (r"^严格 OOS 回测完成。$", r"Strict OOS backtest completed."),
    (r"^報單價格不在漲跌停區間$", r"Order price is outside the daily price limit range."),
    (r"^报单价格不在涨跌停区间$", r"Order price is outside the daily price limit range."),
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
