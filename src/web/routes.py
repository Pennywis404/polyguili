"""
Routes du dashboard — pages HTML + endpoints API pour HTMX.
"""
import csv
import io
from datetime import datetime
from typing import Optional

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


# --- API endpoints pour HTMX ---

@router.get("/api/metrics", response_class=HTMLResponse)
async def api_metrics(request: Request):
    tracker = request.app.state.tracker
    p = tracker.get_portfolio_summary()
    pnl_class = "text-green-400" if p["total_pnl"] >= 0 else "text-red-400"
    pnl_sign = "+" if p["total_pnl"] >= 0 else ""

    return f"""
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div class="bg-gray-800 rounded-xl p-4 border border-gray-700">
            <p class="text-gray-400 text-sm">Capital disponible</p>
            <p class="text-2xl font-bold text-white">${p['current_capital']:,.2f}</p>
            <p class="text-gray-500 text-xs">Deploye: ${p['total_deployed']:,.2f}</p>
        </div>
        <div class="bg-gray-800 rounded-xl p-4 border border-gray-700">
            <p class="text-gray-400 text-sm">P&L Total</p>
            <p class="text-2xl font-bold {pnl_class}">{pnl_sign}${p['total_pnl']:,.4f}</p>
            <p class="text-gray-500 text-xs">Fees: ${p['total_fees_paid']:,.4f}</p>
        </div>
        <div class="bg-gray-800 rounded-xl p-4 border border-gray-700">
            <p class="text-gray-400 text-sm">Trades</p>
            <p class="text-2xl font-bold text-white">{len(p['active_positions'])} / {p['total_trades']}</p>
            <p class="text-gray-500 text-xs">Actifs / Total</p>
        </div>
        <div class="bg-gray-800 rounded-xl p-4 border border-gray-700">
            <p class="text-gray-400 text-sm">Win Rate</p>
            <p class="text-2xl font-bold text-white">{p['win_rate']:.1f}%</p>
            <p class="text-gray-500 text-xs">W:{p['winning_trades']} L:{p['losing_trades']}</p>
        </div>
    </div>
    """


@router.get("/api/pairs", response_class=HTMLResponse)
async def api_pairs(request: Request):
    tracker = request.app.state.tracker
    latest = tracker.get_latest_prices()

    if not latest:
        return '<p class="text-gray-500 text-center py-4">En attente de donnees...</p>'

    rows = ""
    for pair_id, data in sorted(latest.items(), key=lambda x: x[1].get("asset", "")):
        combined = data.get("combined_cost", 0)
        spread = 1.0 - combined
        if combined < 0.97:
            color = "text-green-400"
            bg = "bg-green-900/20"
        elif combined < 1.0:
            color = "text-yellow-400"
            bg = "bg-yellow-900/10"
        else:
            color = "text-red-400"
            bg = ""

        rows += f"""
        <tr class="{bg} border-b border-gray-700/50 hover:bg-gray-700/30">
            <td class="px-3 py-2 font-medium text-white">{data.get('asset', '?')}</td>
            <td class="px-3 py-2 text-gray-300">{data.get('timeframe', '?')}</td>
            <td class="px-3 py-2 text-blue-400">{data.get('best_ask_up', 0):.4f}</td>
            <td class="px-3 py-2 text-purple-400">{data.get('best_ask_down', 0):.4f}</td>
            <td class="px-3 py-2 {color} font-bold">{combined:.4f}</td>
            <td class="px-3 py-2 text-gray-400">{spread:+.4f}</td>
        </tr>
        """

    return f"""
    <table class="w-full text-sm">
        <thead>
            <tr class="text-gray-400 text-xs uppercase border-b border-gray-700">
                <th class="px-3 py-2 text-left">Asset</th>
                <th class="px-3 py-2 text-left">TF</th>
                <th class="px-3 py-2 text-left">Ask Up</th>
                <th class="px-3 py-2 text-left">Ask Down</th>
                <th class="px-3 py-2 text-left">Combined</th>
                <th class="px-3 py-2 text-left">Spread</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>
    """


@router.get("/api/opportunities", response_class=HTMLResponse)
async def api_opportunities(request: Request):
    tracker = request.app.state.tracker
    opps = tracker.get_recent_opportunities(limit=10)

    if not opps:
        return '<p class="text-gray-500 text-center py-4">Aucune opportunite detectee</p>'

    rows = ""
    for opp in opps:
        rows += f"""
        <tr class="border-b border-gray-700/50 hover:bg-gray-700/30">
            <td class="px-3 py-2 text-white font-medium">{opp.get('asset', '?')}</td>
            <td class="px-3 py-2 text-gray-300">{opp.get('timeframe', '?')}</td>
            <td class="px-3 py-2 text-yellow-400">{opp.get('combined_cost', 0):.4f}</td>
            <td class="px-3 py-2 text-green-400">{opp.get('estimated_profit_pct', 0):.2f}%</td>
            <td class="px-3 py-2 text-gray-400">${opp.get('available_liquidity', 0):,.0f}</td>
            <td class="px-3 py-2 text-gray-500 text-xs">{opp.get('timestamp', '')[:19]}</td>
        </tr>
        """

    return f"""
    <table class="w-full text-sm">
        <thead>
            <tr class="text-gray-400 text-xs uppercase border-b border-gray-700">
                <th class="px-3 py-2 text-left">Asset</th>
                <th class="px-3 py-2 text-left">TF</th>
                <th class="px-3 py-2 text-left">Combined</th>
                <th class="px-3 py-2 text-left">ROI Est.</th>
                <th class="px-3 py-2 text-left">Liquidite</th>
                <th class="px-3 py-2 text-left">Heure</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>
    """


@router.get("/api/positions", response_class=HTMLResponse)
async def api_positions(request: Request):
    tracker = request.app.state.tracker
    active = tracker.get_active_trades()

    if not active:
        return '<p class="text-gray-500 text-center py-4">Aucune position ouverte</p>'

    rows = ""
    for trade in active:
        remaining = ""
        if trade.resolution_time:
            delta = (trade.resolution_time - datetime.utcnow()).total_seconds()
            if delta > 0:
                mins, secs = divmod(int(delta), 60)
                remaining = f"{mins}m{secs:02d}s"
                color = "text-green-400" if delta > 60 else "text-red-400"
            else:
                remaining = "Resolving..."
                color = "text-yellow-400"
        else:
            color = "text-gray-400"

        rows += f"""
        <tr class="border-b border-gray-700/50 hover:bg-gray-700/30">
            <td class="px-3 py-2 text-white font-mono text-xs">{trade.id}</td>
            <td class="px-3 py-2 text-white">{trade.asset}</td>
            <td class="px-3 py-2 text-gray-300">{trade.timeframe}</td>
            <td class="px-3 py-2 text-gray-300">${trade.capital_deployed:.2f}</td>
            <td class="px-3 py-2 text-gray-400">{trade.leg1_price:.3f} / {trade.leg2_price or 0:.3f}</td>
            <td class="px-3 py-2 {color} font-mono">{remaining}</td>
            <td class="px-3 py-2">
                <span class="px-2 py-0.5 rounded text-xs bg-blue-900/50 text-blue-300">{trade.status.value}</span>
            </td>
        </tr>
        """

    return f"""
    <table class="w-full text-sm">
        <thead>
            <tr class="text-gray-400 text-xs uppercase border-b border-gray-700">
                <th class="px-3 py-2 text-left">ID</th>
                <th class="px-3 py-2 text-left">Asset</th>
                <th class="px-3 py-2 text-left">TF</th>
                <th class="px-3 py-2 text-left">Capital</th>
                <th class="px-3 py-2 text-left">Prix L1/L2</th>
                <th class="px-3 py-2 text-left">Resolution</th>
                <th class="px-3 py-2 text-left">Status</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>
    """


@router.get("/api/pnl-data")
async def api_pnl_data(request: Request):
    tracker = request.app.state.tracker
    return tracker.get_pnl_data()


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
