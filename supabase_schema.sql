-- Polyarb Supabase Schema
-- Run this in the Supabase SQL Editor

-- Trades table
create table if not exists trades (
    id text primary key,
    pair_id text not null,
    asset text not null,
    timeframe text not null,

    -- Leg 1
    leg1_side text not null,
    leg1_price double precision not null,
    leg1_shares double precision not null,
    leg1_fee double precision not null,
    leg1_timestamp timestamptz not null,
    leg1_stake double precision not null,

    -- Leg 2
    leg2_side text,
    leg2_price double precision,
    leg2_shares double precision,
    leg2_fee double precision,
    leg2_timestamp timestamptz,
    leg2_stake double precision,

    -- Result
    status text not null default 'leg1_open',
    capital_deployed double precision not null default 0,
    total_fees double precision not null default 0,
    payout double precision,
    profit double precision,
    roi double precision,
    resolution_outcome text,
    resolved_at timestamptz,
    resolution_time timestamptz,

    created_at timestamptz not null default now()
);

-- Opportunities table
create table if not exists opportunities (
    id text primary key,
    pair_id text not null,
    asset text not null,
    timeframe text not null,
    leg1_side text not null,
    leg1_price double precision not null,
    leg2_price double precision not null,
    timestamp timestamptz not null,
    combined_cost double precision not null,
    estimated_profit_pct double precision not null,
    available_liquidity double precision not null,
    status text not null default 'detected',

    created_at timestamptz not null default now()
);

-- Portfolio state (single row)
create table if not exists portfolio_state (
    id int primary key default 1 check (id = 1),
    initial_capital double precision not null default 10000,
    current_capital double precision not null default 10000,
    total_deployed double precision not null default 0,
    total_pnl double precision not null default 0,
    total_fees_paid double precision not null default 0,
    total_trades int not null default 0,
    winning_trades int not null default 0,
    losing_trades int not null default 0,
    active_positions jsonb not null default '[]',

    updated_at timestamptz not null default now()
);

-- Insert default portfolio row
insert into portfolio_state (id) values (1) on conflict do nothing;

-- Indexes
create index if not exists idx_trades_asset on trades(asset);
create index if not exists idx_trades_status on trades(status);
create index if not exists idx_trades_created on trades(created_at desc);
create index if not exists idx_opportunities_asset on opportunities(asset);
create index if not exists idx_opportunities_created on opportunities(created_at desc);

-- RLS (Row Level Security) — disable for service role usage
alter table trades enable row level security;
alter table opportunities enable row level security;
alter table portfolio_state enable row level security;

-- Allow all operations with service_role key
create policy "Service role full access" on trades for all using (true) with check (true);
create policy "Service role full access" on opportunities for all using (true) with check (true);
create policy "Service role full access" on portfolio_state for all using (true) with check (true);
