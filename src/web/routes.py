"""
Routes du dashboard — pages HTML + endpoints API pour HTMX.
"""
import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    tracker = request.app.state.tracker
    templates = request.app.state.templates
    pairs_ref = request.app.state.pairs_ref

    return templates.TemplateResponse(request, "dashboard.html", {
        "portfolio": tracker.get_portfolio_summary(),
        "active_trades": tracker.get_active_trades(),
        "opportunities": tracker.get_recent_opportunities(limit=10),
        "pairs": pairs_ref,
        "latest_prices": tracker.get_latest_prices(),
        "pnl_data": tracker.get_pnl_data(),
    })


@router.get("/trades", response_class=HTMLResponse)
async def trades_page(request: Request):
    tracker = request.app.state.tracker
    templates = request.app.state.templates
    asset = request.query_params.get("asset")
    timeframe = request.query_params.get("timeframe")
    status = request.query_params.get("status")
    trades = tracker.get_trade_history(asset=asset, timeframe=timeframe, status=status)

    return templates.TemplateResponse(request, "trades.html", {
        "trades": trades,
        "filter_asset": asset or "",
        "filter_timeframe": timeframe or "",
        "filter_status": status or "",
    })


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "settings.html")


# --- HTMX Partials ---

@router.get("/api/metrics", response_class=HTMLResponse)
async def api_metrics(request: Request):
    tracker = request.app.state.tracker
    p = tracker.get_portfolio_summary()
    pnl_cls = "text-accent-green" if p["total_pnl"] >= 0 else "text-accent-red"
    glow = "glow-green" if p["total_pnl"] >= 0 else "glow-red"
    sign = "+" if p["total_pnl"] >= 0 else ""

    return f"""
    <div class="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <div class="glass rounded-xl p-4">
            <p class="text-gray-500 text-[11px] uppercase tracking-wider mb-1">Capital</p>
            <p class="text-xl font-semibold text-white font-mono">${p['current_capital']:,.2f}</p>
            <p class="text-[10px] text-gray-600 mt-1">Deploye: ${p['total_deployed']:,.2f}</p>
        </div>
        <div class="glass rounded-xl p-4 {glow}">
            <p class="text-gray-500 text-[11px] uppercase tracking-wider mb-1">P&L</p>
            <p class="text-xl font-semibold font-mono {pnl_cls}">{sign}${p['total_pnl']:,.4f}</p>
            <p class="text-[10px] text-gray-600 mt-1">Fees: ${p['total_fees_paid']:,.4f}</p>
        </div>
        <div class="glass rounded-xl p-4">
            <p class="text-gray-500 text-[11px] uppercase tracking-wider mb-1">Trades</p>
            <p class="text-xl font-semibold text-white font-mono">{len(p['active_positions'])}<span class="text-gray-500 text-sm"> / {p['total_trades']}</span></p>
            <p class="text-[10px] text-gray-600 mt-1">Actifs / Total</p>
        </div>
        <div class="glass rounded-xl p-4">
            <p class="text-gray-500 text-[11px] uppercase tracking-wider mb-1">Win Rate</p>
            <p class="text-xl font-semibold text-white font-mono">{p['win_rate']:.1f}%</p>
            <p class="text-[10px] text-gray-600 mt-1">W:{p['winning_trades']} L:{p['losing_trades']}</p>
        </div>
        <div class="glass rounded-xl p-4">
            <p class="text-gray-500 text-[11px] uppercase tracking-wider mb-1">Strategie</p>
            <p class="text-sm font-medium text-accent-purple mt-0.5">Temporal Arb</p>
            <p class="text-[10px] text-gray-600 mt-1">Entry &lt; $0.50</p>
        </div>
    </div>
    """


@router.get("/api/pairs", response_class=HTMLResponse)
async def api_pairs(request: Request):
    tracker = request.app.state.tracker
    latest = tracker.get_latest_prices()

    if not latest:
        return '<p class="text-gray-600 text-center py-8 text-sm">En attente de donnees...</p>'

    rows = ""
    for pair_id, data in sorted(latest.items(), key=lambda x: x[1].get("resolution_time", "")):
        combined = data.get("combined_cost", 0)
        up = data.get("best_ask_up", 0)
        down = data.get("best_ask_down", 0)
        spread = 1.0 - combined

        # Color based on combined cost
        if combined > 0 and combined < 0.98:
            row_bg = "bg-accent-green/5 border-l-2 border-accent-green"
        elif combined > 0 and combined < 1.0:
            row_bg = "border-l-2 border-accent-yellow/30"
        else:
            row_bg = "border-l-2 border-transparent"

        # Resolution countdown
        res_str = ""
        try:
            res_time = datetime.fromisoformat(data.get("resolution_time", ""))
            delta = (res_time - datetime.now(timezone.utc)).total_seconds()
            if delta > 0:
                m, s = divmod(int(delta), 60)
                res_str = f"{m}:{s:02d}"
            else:
                res_str = "Resolving"
        except Exception:
            res_str = "—"

        # Up/Down bar visualization
        up_pct = int(up * 100) if up > 0 else 50
        down_pct = 100 - up_pct

        rows += f"""
        <div class="px-4 py-2.5 {row_bg} hover:bg-white/[0.02] transition-colors">
            <div class="flex items-center justify-between mb-1.5">
                <div class="flex items-center gap-2">
                    <span class="font-mono text-xs text-gray-400">{res_str}</span>
                </div>
                <span class="font-mono text-[11px] {'text-accent-green' if spread > 0 else 'text-gray-500'}">{combined:.4f}</span>
            </div>
            <div class="flex items-center gap-1 h-6 rounded overflow-hidden">
                <div class="h-full rounded-l flex items-center justify-center text-[10px] font-mono font-medium"
                     style="width:{up_pct}%; background: rgba(0,212,170,0.15); color: #00d4aa;">
                    Up {up:.3f}
                </div>
                <div class="h-full rounded-r flex items-center justify-center text-[10px] font-mono font-medium"
                     style="width:{down_pct}%; background: rgba(255,71,87,0.15); color: #ff4757;">
                    Down {down:.3f}
                </div>
            </div>
        </div>
        """

    return f'<div class="divide-y divide-white/[0.03]">{rows}</div>'


@router.get("/api/positions", response_class=HTMLResponse)
async def api_positions(request: Request):
    """Tracker des positions avec statut Leg1/Leg2 — vue style Polymarket."""
    tracker = request.app.state.tracker
    active = tracker.get_active_trades()
    latest_prices = tracker.get_latest_prices()

    if not active:
        return '<p class="text-gray-600 text-center py-8 text-sm">Aucune position ouverte</p>'

    rows = ""
    for trade in active:
        # Current market price
        current = latest_prices.get(trade.pair_id, {})
        current_up = current.get("best_ask_up", 0)
        current_down = current.get("best_ask_down", 0)

        # Leg 1 info
        l1_side = trade.leg1_side.value.upper()
        l1_price = trade.leg1_price
        l1_color = "text-accent-green" if l1_side == "UP" else "text-accent-red"
        l1_current = current_up if l1_side == "UP" else current_down
        l1_delta = l1_current - l1_price if l1_current > 0 else 0
        l1_delta_cls = "text-accent-green" if l1_delta >= 0 else "text-accent-red"

        # Leg 2 info
        if trade.leg2_price is not None:
            l2_side = trade.leg2_side.value.upper() if trade.leg2_side else "—"
            l2_price = trade.leg2_price
            l2_color = "text-accent-green" if l2_side == "UP" else "text-accent-red"
            l2_badge = f'<span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-accent-green/10 text-accent-green">HEDGED</span>'
            combined = trade.leg1_price + trade.leg2_price
            profit_est = f'<span class="font-mono text-accent-green">${(1.0/(combined) * trade.capital_deployed - trade.capital_deployed):.2f}</span>' if combined < 1.0 else '<span class="font-mono text-accent-red">—</span>'
        else:
            l2_side = "DOWN" if l1_side == "UP" else "UP"
            l2_price = current_down if l1_side == "UP" else current_up
            l2_color = "text-accent-red" if l1_side == "UP" else "text-accent-green"
            l2_badge = f'<span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-accent-yellow/10 text-accent-yellow">WAITING</span>'
            profit_est = '<span class="text-gray-600 text-xs">en attente leg2</span>'

        # Resolution countdown
        remaining = ""
        remaining_cls = "text-gray-500"
        if trade.resolution_time:
            delta = (trade.resolution_time - datetime.now(timezone.utc)).total_seconds()
            if delta > 0:
                m, s = divmod(int(delta), 60)
                remaining = f"{m}:{s:02d}"
                remaining_cls = "text-accent-green" if delta > 60 else "text-accent-red"
            else:
                remaining = "Resolving..."
                remaining_cls = "text-accent-yellow"

        rows += f"""
        <div class="px-4 py-3 hover:bg-white/[0.02] transition-colors border-b border-white/[0.03] fade-in">
            <div class="flex items-center justify-between mb-2">
                <div class="flex items-center gap-2">
                    <span class="text-white font-medium text-sm">{trade.asset}</span>
                    <span class="text-gray-500 text-xs">{trade.timeframe}</span>
                    <span class="font-mono text-[10px] text-gray-600">{trade.id}</span>
                </div>
                <div class="flex items-center gap-2">
                    {l2_badge}
                    <span class="font-mono text-xs {remaining_cls}">{remaining}</span>
                </div>
            </div>
            <div class="grid grid-cols-3 gap-3">
                <!-- Leg 1 -->
                <div class="glass-light rounded-lg p-2.5">
                    <div class="flex items-center justify-between mb-1">
                        <span class="text-[10px] text-gray-500 uppercase">Leg 1 — {l1_side}</span>
                        <span class="text-[10px] font-mono {l1_delta_cls}">{l1_delta:+.3f}</span>
                    </div>
                    <div class="flex items-baseline gap-1">
                        <span class="font-mono text-lg font-semibold {l1_color}">{l1_price:.3f}</span>
                        <span class="text-[10px] text-gray-600">→ {l1_current:.3f}</span>
                    </div>
                    <div class="mt-1 h-1 rounded bg-surface-700">
                        <div class="h-full rounded bg-accent-green" style="width:100%"></div>
                    </div>
                    <p class="text-[9px] text-gray-600 mt-1">${trade.leg1_stake:.2f} · {trade.leg1_shares:.0f} shares</p>
                </div>
                <!-- Leg 2 -->
                <div class="glass-light rounded-lg p-2.5 {'opacity-50' if trade.leg2_price is None else ''}">
                    <div class="flex items-center justify-between mb-1">
                        <span class="text-[10px] text-gray-500 uppercase">Leg 2 — {l2_side}</span>
                    </div>
                    <div class="flex items-baseline gap-1">
                        <span class="font-mono text-lg font-semibold {l2_color}">{'%.3f' % l2_price if l2_price else '—'}</span>
                        <span class="text-[10px] text-gray-600">{'actuel' if trade.leg2_price is None else 'locked'}</span>
                    </div>
                    <div class="mt-1 h-1 rounded bg-surface-700">
                        <div class="h-full rounded {'bg-accent-green' if trade.leg2_price else 'bg-accent-yellow'}" style="width:{'100' if trade.leg2_price else '0'}%"></div>
                    </div>
                    <p class="text-[9px] text-gray-600 mt-1">{'$%.2f · %.0f shares' % (trade.leg2_stake, trade.leg2_shares) if trade.leg2_price else 'En attente < $0.50'}</p>
                </div>
                <!-- Profit -->
                <div class="glass-light rounded-lg p-2.5 flex flex-col justify-center items-center">
                    <span class="text-[10px] text-gray-500 uppercase mb-1">Profit Est.</span>
                    {profit_est}
                    <p class="text-[9px] text-gray-600 mt-1">${trade.capital_deployed:.2f} deploye</p>
                </div>
            </div>
        </div>
        """

    return rows


@router.get("/api/opportunities", response_class=HTMLResponse)
async def api_opportunities(request: Request):
    tracker = request.app.state.tracker
    opps = tracker.get_recent_opportunities(limit=10)

    if not opps:
        return '<p class="text-gray-600 text-center py-8 text-sm">Aucun signal</p>'

    rows = ""
    for opp in opps:
        side = opp.get("leg1_side", "?").upper()
        side_cls = "text-accent-green" if side == "UP" else "text-accent-red"
        ts = opp.get("timestamp", "")[:19].split("T")[-1] if "T" in opp.get("timestamp", "") else ""

        rows += f"""
        <div class="px-4 py-2 hover:bg-white/[0.02] transition-colors border-b border-white/[0.03]">
            <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                    <span class="{side_cls} font-mono text-xs font-medium">{side} {opp.get('leg1_price', 0):.3f}</span>
                    <span class="text-gray-600 text-[10px]">→ combined {opp.get('combined_cost', 0):.4f}</span>
                </div>
                <span class="text-gray-600 font-mono text-[10px]">{ts}</span>
            </div>
        </div>
        """

    return rows


@router.get("/api/history", response_class=HTMLResponse)
async def api_history(request: Request):
    """5 derniers trades resolus."""
    tracker = request.app.state.tracker
    trades = [t for t in tracker.get_trade_history() if t.status.value.startswith("resolved")][:5]

    if not trades:
        return '<p class="text-gray-600 text-center py-8 text-sm">Aucun trade resolu</p>'

    rows = ""
    for t in trades:
        is_win = t.status.value == "resolved_win"
        status_badge = '<span class="text-[10px] px-1.5 py-0.5 rounded bg-accent-green/10 text-accent-green font-mono">WIN</span>' if is_win else '<span class="text-[10px] px-1.5 py-0.5 rounded bg-accent-red/10 text-accent-red font-mono">LOSS</span>'
        profit_cls = "text-accent-green" if (t.profit or 0) >= 0 else "text-accent-red"

        rows += f"""
        <div class="px-4 py-2.5 hover:bg-white/[0.02] transition-colors border-b border-white/[0.03]">
            <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                    {status_badge}
                    <span class="text-gray-400 text-xs">{t.leg1_price:.3f} + {t.leg2_price:.3f if t.leg2_price else '—'}</span>
                </div>
                <div class="flex items-center gap-3">
                    <span class="font-mono text-xs {profit_cls}">{'$%.4f' % t.profit if t.profit is not None else '—'}</span>
                    <span class="font-mono text-[10px] text-gray-600">{'%.1f%%' % t.roi if t.roi is not None else ''}</span>
                </div>
            </div>
        </div>
        """

    return rows


@router.get("/api/pnl-data")
async def api_pnl_data(request: Request):
    tracker = request.app.state.tracker
    return tracker.get_pnl_data()


@router.get("/api/chart-data")
async def api_chart_data(request: Request):
    tracker = request.app.state.tracker
    asset = request.query_params.get("asset")
    return tracker.get_chart_data(asset=asset)


@router.get("/api/available-assets")
async def api_available_assets(request: Request):
    tracker = request.app.state.tracker
    return tracker.get_available_assets()


@router.get("/api/export/csv")
async def export_csv(request: Request):
    tracker = request.app.state.tracker
    trades = tracker.get_trade_history()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "asset", "timeframe", "status",
        "leg1_side", "leg1_price", "leg2_price",
        "capital_deployed", "total_fees", "payout", "profit", "roi",
        "leg1_timestamp", "resolved_at",
    ])
    for t in trades:
        writer.writerow([
            t.id, t.asset, t.timeframe, t.status.value,
            t.leg1_side.value, t.leg1_price, t.leg2_price or "",
            t.capital_deployed, t.total_fees, t.payout or "", t.profit or "", t.roi or "",
            t.leg1_timestamp.isoformat(), t.resolved_at.isoformat() if t.resolved_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=trades_export.csv"},
    )
