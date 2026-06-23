-- ─────────────────────────────────────────
-- CRE Outreach Intelligence — Supabase Schema
-- Run once in Supabase SQL editor
-- ─────────────────────────────────────────

-- 1. Users (one row per broker — populated by Google OAuth later)
create table if not exists users (
    id                  uuid primary key default gen_random_uuid(),
    google_email        text unique not null,
    full_name           text,
    google_token        jsonb,
    telegram_chat_id    text,
    telegram_connected  boolean default false,
    active_icp_profile  text default 'healthcare_tech_nyc',
    firm_name           text default 'CRE Partners',
    sign_off            text default 'Best, Michael',
    created_at          timestamptz default now(),
    last_login          timestamptz default now()
);

-- 2. Sessions (login tokens — populated by OAuth later)
create table if not exists sessions (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid references users(id),
    google_email    text,
    session_token   text unique not null,
    created_at      timestamptz default now(),
    expires_at      timestamptz default (now() + interval '30 days')
);

-- 3. Prospects / watchlist
create table if not exists prospects (
    id              text primary key,
    company         text not null,
    domain          text,
    contact_name    text,
    contact_title   text,
    contact_email   text,
    linkedin_url    text,
    sector          text,
    city            text default 'New York',
    icp_profile     text,
    source          text default 'watchlist',
    approved        boolean default true,
    active          boolean default true,
    dismissed       boolean default false,
    added_at        timestamptz default now(),
    discovered_at   timestamptz
);

-- 4. Research reports (one per prospect per day)
create table if not exists research_reports (
    id               uuid primary key default gen_random_uuid(),
    prospect_id      text references prospects(id),
    company          text,
    contact_name     text,
    contact_title    text,
    contact_email    text,
    composite_score  integer,
    tier             text,
    signals          jsonb default '[]',
    draft            jsonb,
    top_hook         text,
    skip_today       boolean default false,
    skip_reason      text,
    source           text default 'watchlist',
    generated_at     timestamptz default now(),
    run_date         date default current_date
);

-- 5. Sent emails
create table if not exists sent_emails (
    id                  uuid primary key default gen_random_uuid(),
    prospect_id         text,
    company             text,
    contact_name        text,
    contact_title       text,
    contact_email       text,
    linkedin_url        text,
    email_subject       text,
    email_body          text,
    linkedin_message    text,
    research_signals    jsonb default '[]',
    score               integer,
    tier                text,
    tone_variant        text,
    top_signal_used     text,
    status              text default 'Sent',
    sent_at             timestamptz default now(),
    reply_date          timestamptz,
    reply_content       text,
    followup_date       date,
    calendar_event_id   text,
    gmail_message_id    text,
    notes               text
);

-- 6. Approved emails (for tone learning)
create table if not exists approved_emails (
    id           uuid primary key default gen_random_uuid(),
    subject      text,
    body         text,
    company      text,
    tone_variant text,
    saved_at     timestamptz default now()
);

-- 7. Tone profile (single row, upserted)
create table if not exists tone_profiles (
    id         integer primary key default 1,
    profile    jsonb not null,
    updated_at timestamptz default now()
);

-- 8. Pipeline run log
create table if not exists pipeline_runs (
    id               uuid primary key default gen_random_uuid(),
    run_date         date default current_date,
    status           text,
    prospects_count  integer default 0,
    drafts_count     integer default 0,
    skipped_count    integer default 0,
    error            text,
    started_at       timestamptz default now(),
    completed_at     timestamptz
);

-- 9. OAuth tokens (gmail / sheets / calendar per user)
create table if not exists oauth_tokens (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid references users(id),
    token_type   text not null,
    token_data   jsonb not null,
    updated_at   timestamptz default now(),
    unique(user_id, token_type)
);

-- 10. Dismissed leads
create table if not exists dismissed_leads (
    id           text primary key,
    dismissed_at timestamptz default now()
);

-- 11. Score cache (avoid re-calling HF for same input)
create table if not exists score_cache (
    cache_key    text primary key,
    result       jsonb not null,
    created_at   timestamptz default now()
);

-- 12. OAuth PKCE State Store (survives worker restarts)
create table if not exists oauth_state (
    state           text primary key,
    code_verifier   text not null,
    created_at      timestamptz default now(),
    expires_at      timestamptz not null
);


-- Indexes
create index if not exists idx_sessions_token       on sessions(session_token);
create index if not exists idx_sessions_expires     on sessions(expires_at);
create index if not exists idx_research_run_date    on research_reports(run_date);
create index if not exists idx_research_prospect    on research_reports(prospect_id);
create index if not exists idx_sent_contact         on sent_emails(contact_email);
create index if not exists idx_sent_at              on sent_emails(sent_at desc);
create index if not exists idx_prospects_active     on prospects(active, approved);
create index if not exists idx_pipeline_run_date    on pipeline_runs(run_date desc);
