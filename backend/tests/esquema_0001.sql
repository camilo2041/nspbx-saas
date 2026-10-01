-- Esquema de la revisión 0001_base, congelado (pg_dump --schema-only).
-- Lo usa tests/test_migraciones.py para comprobar que una base creada con
-- este esquema y llevada a la última revisión coincide con los modelos: si
-- alguien cambia un modelo sin escribir la revisión, esa prueba falla.
-- NO se regenera: es la foto del punto de partida.

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

COMMENT ON SCHEMA public IS '';

CREATE FUNCTION public.audit_log_inmutable() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          RAISE EXCEPTION 'audit_log es de solo agregar';
        END $$;

SET default_tablespace = '';

SET default_table_access_method = heap;

CREATE TABLE public.ai_call_usage (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    call_uuid character varying(64) NOT NULL,
    phone character varying(30),
    turns integer NOT NULL,
    tts_chars integer NOT NULL,
    tts_provider character varying(20),
    stt_provider character varying(20),
    stt_seconds integer NOT NULL,
    llm_calls integer NOT NULL,
    llm_prompt_tokens integer NOT NULL,
    llm_completion_tokens integer NOT NULL,
    outcome character varying(20) NOT NULL,
    resolved boolean NOT NULL,
    action character varying(20),
    appointment_id integer,
    action_appointment_date timestamp without time zone,
    action_patient_name character varying(150),
    duration_seconds integer NOT NULL,
    started_at timestamp without time zone NOT NULL,
    ended_at timestamp without time zone
);

CREATE SEQUENCE public.ai_call_usage_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.ai_call_usage_id_seq OWNED BY public.ai_call_usage.id;

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);

CREATE TABLE public.appointments (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    patient_name character varying(150) NOT NULL,
    phone character varying(30) NOT NULL,
    appointment_date timestamp without time zone NOT NULL,
    duration_minutes integer NOT NULL,
    status character varying(20) NOT NULL,
    confirmed_at timestamp without time zone,
    notes text,
    created_at timestamp without time zone NOT NULL
);

CREATE SEQUENCE public.appointments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.appointments_id_seq OWNED BY public.appointments.id;

CREATE TABLE public.audit_log (
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    tenant_id integer,
    user_id integer,
    actor character varying(100),
    action character varying(120) NOT NULL,
    resource character varying(120),
    detail json,
    result character varying(12) NOT NULL,
    ip character varying(64),
    user_agent character varying(200),
    request_id character varying(64)
);

CREATE SEQUENCE public.audit_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.audit_log_id_seq OWNED BY public.audit_log.id;

CREATE TABLE public.call_logs (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    campaign_id integer,
    extension_id integer,
    uuid character varying(64),
    caller_number character varying(30),
    caller_name character varying(100),
    callee_number character varying(30),
    direction character varying(10) NOT NULL,
    status character varying(20) NOT NULL,
    duration integer NOT NULL,
    billsec integer NOT NULL,
    hangup_cause character varying(50),
    via_trunk boolean,
    recording_path character varying(500),
    summary text,
    started_at timestamp without time zone,
    answered_at timestamp without time zone,
    ended_at timestamp without time zone
);

CREATE SEQUENCE public.call_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.call_logs_id_seq OWNED BY public.call_logs.id;

CREATE TABLE public.campaign_numbers (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    campaign_id integer NOT NULL,
    phone character varying(30) NOT NULL,
    status character varying(20) NOT NULL,
    attempts integer NOT NULL,
    last_error text,
    extra_data text,
    appointment_id integer,
    created_at timestamp without time zone NOT NULL
);

CREATE SEQUENCE public.campaign_numbers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.campaign_numbers_id_seq OWNED BY public.campaign_numbers.id;

CREATE TABLE public.campaigns (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    name character varying(100) NOT NULL,
    trunk_id integer,
    voicebot_id integer,
    max_concurrency integer NOT NULL,
    retries integer NOT NULL,
    status character varying(20) NOT NULL,
    ai_intent character varying(30),
    message_template text,
    created_at timestamp without time zone NOT NULL,
    started_at timestamp without time zone,
    finished_at timestamp without time zone
);

CREATE SEQUENCE public.campaigns_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.campaigns_id_seq OWNED BY public.campaigns.id;

CREATE TABLE public.debts (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    phone character varying(30) NOT NULL,
    debtor_name character varying(150) NOT NULL,
    amount double precision NOT NULL,
    due_date timestamp without time zone,
    invoice_number character varying(50),
    notes text,
    status character varying(20) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);

CREATE SEQUENCE public.debts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.debts_id_seq OWNED BY public.debts.id;

CREATE TABLE public.device_tokens (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    user_id integer NOT NULL,
    extension_id integer,
    platform character varying(20) NOT NULL,
    token_type character varying(20) NOT NULL,
    token character varying(255) NOT NULL,
    updated_at timestamp without time zone NOT NULL
);

CREATE SEQUENCE public.device_tokens_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.device_tokens_id_seq OWNED BY public.device_tokens.id;

CREATE TABLE public.extensions (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    number character varying(20) NOT NULL,
    password character varying(255) NOT NULL,
    caller_id_name character varying(100),
    voicemail boolean NOT NULL,
    enabled boolean NOT NULL,
    created_at timestamp without time zone NOT NULL
);

CREATE SEQUENCE public.extensions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.extensions_id_seq OWNED BY public.extensions.id;

CREATE TABLE public.inbound_routes (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    name character varying(100) NOT NULL,
    did_pattern character varying(100) NOT NULL,
    destination_type character varying(20) NOT NULL,
    destination_value character varying(50),
    priority integer NOT NULL,
    enabled boolean NOT NULL,
    created_at timestamp without time zone NOT NULL
);

CREATE SEQUENCE public.inbound_routes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.inbound_routes_id_seq OWNED BY public.inbound_routes.id;

CREATE TABLE public.licenses (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    plan character varying(30) NOT NULL,
    status character varying(20) NOT NULL,
    started_at timestamp without time zone,
    expires_at timestamp without time zone,
    max_extensions integer,
    max_trunks integer,
    max_concurrent_calls integer,
    max_campaigns integer,
    max_outbound_minutes_day integer,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);

CREATE SEQUENCE public.licenses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.licenses_id_seq OWNED BY public.licenses.id;

CREATE TABLE public.outbound_routes (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    name character varying(100) NOT NULL,
    pattern character varying(100) NOT NULL,
    strip_digits integer NOT NULL,
    prepend character varying(20),
    trunk_ids character varying(120) NOT NULL,
    allow_international boolean NOT NULL,
    priority integer NOT NULL,
    enabled boolean NOT NULL,
    created_at timestamp without time zone NOT NULL
);

CREATE SEQUENCE public.outbound_routes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.outbound_routes_id_seq OWNED BY public.outbound_routes.id;

CREATE TABLE public.payment_promises (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    debt_id integer,
    phone character varying(30) NOT NULL,
    debtor_name character varying(150),
    amount_promised double precision NOT NULL,
    promise_date timestamp without time zone NOT NULL,
    plan character varying(20) NOT NULL,
    installments integer,
    notes text,
    status character varying(20) NOT NULL,
    call_uuid character varying(64),
    created_at timestamp without time zone NOT NULL
);

CREATE SEQUENCE public.payment_promises_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.payment_promises_id_seq OWNED BY public.payment_promises.id;

CREATE TABLE public.platform_state (
    id integer NOT NULL,
    outbound_blocked boolean DEFAULT false NOT NULL,
    updated_at timestamp without time zone NOT NULL
);

CREATE SEQUENCE public.platform_state_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.platform_state_id_seq OWNED BY public.platform_state.id;

CREATE TABLE public.queues (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    name character varying(100) NOT NULL,
    extension character varying(30) NOT NULL,
    strategy character varying(40) NOT NULL,
    moh_sound character varying(255) NOT NULL,
    agents text,
    max_wait_time integer NOT NULL,
    max_wait_time_with_no_agent integer NOT NULL,
    agent_ring_timeout integer NOT NULL,
    max_no_answer integer NOT NULL,
    wrap_up_time integer NOT NULL,
    record boolean NOT NULL,
    failover_extension character varying(30),
    announce_position boolean NOT NULL,
    enabled boolean NOT NULL,
    created_at timestamp without time zone NOT NULL
);

CREATE SEQUENCE public.queues_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.queues_id_seq OWNED BY public.queues.id;

CREATE TABLE public.refresh_tokens (
    id integer NOT NULL,
    user_id integer NOT NULL,
    token_hash character varying(64) NOT NULL,
    device_label character varying(150),
    platform character varying(20),
    created_at timestamp without time zone NOT NULL,
    expires_at timestamp without time zone NOT NULL,
    revoked_at timestamp without time zone
);

CREATE SEQUENCE public.refresh_tokens_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.refresh_tokens_id_seq OWNED BY public.refresh_tokens.id;

CREATE TABLE public.role_permissions (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    role character varying(20) NOT NULL,
    permission character varying(50) NOT NULL,
    allowed boolean NOT NULL,
    created_at timestamp without time zone NOT NULL
);

CREATE SEQUENCE public.role_permissions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.role_permissions_id_seq OWNED BY public.role_permissions.id;

CREATE TABLE public.security_alerts (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    kind character varying(30) NOT NULL,
    detail text NOT NULL,
    created_at timestamp without time zone NOT NULL
);

CREATE SEQUENCE public.security_alerts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.security_alerts_id_seq OWNED BY public.security_alerts.id;

CREATE TABLE public.system_settings (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    app_name character varying(100) NOT NULL,
    fs_domain character varying(255) NOT NULL,
    fs_esl_host character varying(255) NOT NULL,
    fs_esl_port integer NOT NULL,
    fs_esl_password character varying(255) NOT NULL,
    fs_http_base character varying(255) NOT NULL,
    sip_ws_url character varying(255) NOT NULL,
    sip_server_ip character varying(255) NOT NULL,
    sip_server_port integer NOT NULL,
    elevenlabs_api_key character varying(255),
    agent_webhook_secret character varying(255),
    ai_llm_provider_name character varying(60) NOT NULL,
    ai_llm_base_url character varying(255) NOT NULL,
    ai_llm_model character varying(100) NOT NULL,
    ai_llm_api_key character varying(255),
    record_all_calls boolean NOT NULL,
    deepgram_api_key character varying(200),
    ai_stt_provider character varying(20) NOT NULL,
    ai_voice_provider character varying(20) NOT NULL,
    ai_voice_id character varying(100) NOT NULL,
    rate_tts_per_1k_chars double precision NOT NULL,
    rate_stt_per_minute double precision NOT NULL,
    rate_dg_tts_per_1k_chars double precision NOT NULL,
    rate_dg_stt_per_minute double precision NOT NULL,
    rate_llm_in_per_1m double precision NOT NULL,
    rate_llm_out_per_1m double precision NOT NULL,
    backup_enabled boolean NOT NULL,
    ari_base_url character varying(255),
    ari_user character varying(80),
    ari_password character varying(255),
    ari_app character varying(80) NOT NULL,
    backup_retention_days integer NOT NULL,
    last_backup_at timestamp without time zone,
    last_backup_ok boolean,
    last_backup_error character varying(500),
    recordings_retention_days integer NOT NULL,
    recordings_max_gb double precision NOT NULL,
    backups_max_gb double precision NOT NULL,
    max_call_duration_minutes integer NOT NULL,
    max_concurrent_calls integer NOT NULL,
    allow_international boolean NOT NULL,
    international_countries character varying(200) DEFAULT ''::character varying NOT NULL,
    outbound_paused boolean DEFAULT false NOT NULL,
    webcall_enabled boolean NOT NULL,
    webcall_queue_id integer,
    webcall_max_concurrent integer NOT NULL,
    webcall_turnstile_site_key character varying(255),
    webcall_turnstile_secret character varying(255),
    webcall_schedule text,
    webcall_greeting character varying(255),
    webcall_button_text character varying(120),
    webcall_offline_text character varying(255),
    updated_at timestamp without time zone NOT NULL
);

CREATE SEQUENCE public.system_settings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.system_settings_id_seq OWNED BY public.system_settings.id;

CREATE TABLE public.tenants (
    id integer NOT NULL,
    name character varying(150) NOT NULL,
    slug character varying(40) NOT NULL,
    sip_domain character varying(255) NOT NULL,
    subdomain character varying(80),
    business_type character varying(30) NOT NULL,
    modules character varying(120) NOT NULL,
    enabled boolean NOT NULL,
    outbound_blocked boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone NOT NULL
);

CREATE SEQUENCE public.tenants_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.tenants_id_seq OWNED BY public.tenants.id;

CREATE TABLE public.trunks (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    name character varying(100) NOT NULL,
    gateway_host character varying(255) NOT NULL,
    gateway_port integer NOT NULL,
    username character varying(100),
    password character varying(255),
    from_domain character varying(255),
    register_enabled boolean NOT NULL,
    caller_id_number character varying(30),
    transport character varying(10) NOT NULL,
    ping integer,
    codec_prefs character varying(255),
    enabled boolean NOT NULL,
    created_at timestamp without time zone NOT NULL
);

CREATE SEQUENCE public.trunks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.trunks_id_seq OWNED BY public.trunks.id;

CREATE TABLE public.users (
    id integer NOT NULL,
    tenant_id integer,
    username character varying(60) NOT NULL,
    full_name character varying(150) NOT NULL,
    email character varying(150),
    password_hash character varying(255) NOT NULL,
    role character varying(20) NOT NULL,
    extension_id integer,
    enabled boolean NOT NULL,
    last_login_at timestamp without time zone,
    sesiones_desde timestamp without time zone,
    mfa_secret character varying(64),
    mfa_enabled boolean DEFAULT false NOT NULL,
    mfa_last_step integer,
    mfa_recovery json,
    created_at timestamp without time zone NOT NULL
);

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;

CREATE TABLE public.voicebots (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    name character varying(100) NOT NULL,
    bot_type character varying(20) NOT NULL,
    welcome_message text,
    config text,
    greeting_audio_path character varying(500),
    flow_json text,
    enabled boolean NOT NULL,
    created_at timestamp without time zone NOT NULL
);

CREATE SEQUENCE public.voicebots_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.voicebots_id_seq OWNED BY public.voicebots.id;

ALTER TABLE ONLY public.ai_call_usage ALTER COLUMN id SET DEFAULT nextval('public.ai_call_usage_id_seq'::regclass);

ALTER TABLE ONLY public.appointments ALTER COLUMN id SET DEFAULT nextval('public.appointments_id_seq'::regclass);

ALTER TABLE ONLY public.audit_log ALTER COLUMN id SET DEFAULT nextval('public.audit_log_id_seq'::regclass);

ALTER TABLE ONLY public.call_logs ALTER COLUMN id SET DEFAULT nextval('public.call_logs_id_seq'::regclass);

ALTER TABLE ONLY public.campaign_numbers ALTER COLUMN id SET DEFAULT nextval('public.campaign_numbers_id_seq'::regclass);

ALTER TABLE ONLY public.campaigns ALTER COLUMN id SET DEFAULT nextval('public.campaigns_id_seq'::regclass);

ALTER TABLE ONLY public.debts ALTER COLUMN id SET DEFAULT nextval('public.debts_id_seq'::regclass);

ALTER TABLE ONLY public.device_tokens ALTER COLUMN id SET DEFAULT nextval('public.device_tokens_id_seq'::regclass);

ALTER TABLE ONLY public.extensions ALTER COLUMN id SET DEFAULT nextval('public.extensions_id_seq'::regclass);

ALTER TABLE ONLY public.inbound_routes ALTER COLUMN id SET DEFAULT nextval('public.inbound_routes_id_seq'::regclass);

ALTER TABLE ONLY public.licenses ALTER COLUMN id SET DEFAULT nextval('public.licenses_id_seq'::regclass);

ALTER TABLE ONLY public.outbound_routes ALTER COLUMN id SET DEFAULT nextval('public.outbound_routes_id_seq'::regclass);

ALTER TABLE ONLY public.payment_promises ALTER COLUMN id SET DEFAULT nextval('public.payment_promises_id_seq'::regclass);

ALTER TABLE ONLY public.platform_state ALTER COLUMN id SET DEFAULT nextval('public.platform_state_id_seq'::regclass);

ALTER TABLE ONLY public.queues ALTER COLUMN id SET DEFAULT nextval('public.queues_id_seq'::regclass);

ALTER TABLE ONLY public.refresh_tokens ALTER COLUMN id SET DEFAULT nextval('public.refresh_tokens_id_seq'::regclass);

ALTER TABLE ONLY public.role_permissions ALTER COLUMN id SET DEFAULT nextval('public.role_permissions_id_seq'::regclass);

ALTER TABLE ONLY public.security_alerts ALTER COLUMN id SET DEFAULT nextval('public.security_alerts_id_seq'::regclass);

ALTER TABLE ONLY public.system_settings ALTER COLUMN id SET DEFAULT nextval('public.system_settings_id_seq'::regclass);

ALTER TABLE ONLY public.tenants ALTER COLUMN id SET DEFAULT nextval('public.tenants_id_seq'::regclass);

ALTER TABLE ONLY public.trunks ALTER COLUMN id SET DEFAULT nextval('public.trunks_id_seq'::regclass);

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);

ALTER TABLE ONLY public.voicebots ALTER COLUMN id SET DEFAULT nextval('public.voicebots_id_seq'::regclass);

ALTER TABLE ONLY public.ai_call_usage
    ADD CONSTRAINT ai_call_usage_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);

ALTER TABLE ONLY public.appointments
    ADD CONSTRAINT appointments_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.call_logs
    ADD CONSTRAINT call_logs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.call_logs
    ADD CONSTRAINT call_logs_uuid_key UNIQUE (uuid);

ALTER TABLE ONLY public.campaign_numbers
    ADD CONSTRAINT campaign_numbers_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.campaigns
    ADD CONSTRAINT campaigns_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.debts
    ADD CONSTRAINT debts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.device_tokens
    ADD CONSTRAINT device_tokens_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.extensions
    ADD CONSTRAINT extensions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.inbound_routes
    ADD CONSTRAINT inbound_routes_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.licenses
    ADD CONSTRAINT licenses_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.outbound_routes
    ADD CONSTRAINT outbound_routes_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.payment_promises
    ADD CONSTRAINT payment_promises_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.platform_state
    ADD CONSTRAINT platform_state_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.queues
    ADD CONSTRAINT queues_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT refresh_tokens_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.security_alerts
    ADD CONSTRAINT security_alerts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.system_settings
    ADD CONSTRAINT system_settings_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.tenants
    ADD CONSTRAINT tenants_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.trunks
    ADD CONSTRAINT trunks_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.campaigns
    ADD CONSTRAINT ux_campaigns_tenant_name UNIQUE (tenant_id, name);

ALTER TABLE ONLY public.device_tokens
    ADD CONSTRAINT ux_device_tokens_tenant_user_platform UNIQUE (tenant_id, user_id, platform);

ALTER TABLE ONLY public.extensions
    ADD CONSTRAINT ux_extensions_tenant_number UNIQUE (tenant_id, number);

ALTER TABLE ONLY public.inbound_routes
    ADD CONSTRAINT ux_inbound_routes_did UNIQUE (did_pattern);

ALTER TABLE ONLY public.licenses
    ADD CONSTRAINT ux_licenses_tenant UNIQUE (tenant_id);

ALTER TABLE ONLY public.queues
    ADD CONSTRAINT ux_queues_tenant_extension UNIQUE (tenant_id, extension);

ALTER TABLE ONLY public.queues
    ADD CONSTRAINT ux_queues_tenant_name UNIQUE (tenant_id, name);

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT ux_role_permissions UNIQUE (tenant_id, role, permission);

ALTER TABLE ONLY public.system_settings
    ADD CONSTRAINT ux_system_settings_tenant UNIQUE (tenant_id);

ALTER TABLE ONLY public.trunks
    ADD CONSTRAINT ux_trunks_tenant_name UNIQUE (tenant_id, name);

ALTER TABLE ONLY public.voicebots
    ADD CONSTRAINT ux_voicebots_tenant_name UNIQUE (tenant_id, name);

ALTER TABLE ONLY public.voicebots
    ADD CONSTRAINT voicebots_pkey PRIMARY KEY (id);

CREATE UNIQUE INDEX ix_ai_call_usage_call_uuid ON public.ai_call_usage USING btree (call_uuid);

CREATE INDEX ix_ai_call_usage_started_at ON public.ai_call_usage USING btree (started_at);

CREATE INDEX ix_ai_call_usage_tenant_id ON public.ai_call_usage USING btree (tenant_id);

CREATE INDEX ix_appointments_tenant_id ON public.appointments USING btree (tenant_id);

CREATE INDEX ix_audit_log_action ON public.audit_log USING btree (action);

CREATE INDEX ix_audit_log_created_at ON public.audit_log USING btree (created_at);

CREATE INDEX ix_audit_log_request_id ON public.audit_log USING btree (request_id);

CREATE INDEX ix_audit_log_tenant_id ON public.audit_log USING btree (tenant_id);

CREATE INDEX ix_call_logs_tenant_id ON public.call_logs USING btree (tenant_id);

CREATE INDEX ix_call_logs_tenant_started ON public.call_logs USING btree (tenant_id, started_at);

CREATE UNIQUE INDEX ix_call_logs_uuid ON public.call_logs USING btree (uuid);

CREATE INDEX ix_campaign_numbers_phone ON public.campaign_numbers USING btree (phone);

CREATE INDEX ix_campaign_numbers_tenant_id ON public.campaign_numbers USING btree (tenant_id);

CREATE INDEX ix_campaigns_tenant_id ON public.campaigns USING btree (tenant_id);

CREATE INDEX ix_debts_phone ON public.debts USING btree (phone);

CREATE INDEX ix_debts_tenant_id ON public.debts USING btree (tenant_id);

CREATE INDEX ix_device_tokens_extension_id ON public.device_tokens USING btree (extension_id);

CREATE INDEX ix_device_tokens_tenant_id ON public.device_tokens USING btree (tenant_id);

CREATE INDEX ix_device_tokens_user_id ON public.device_tokens USING btree (user_id);

CREATE INDEX ix_extensions_number ON public.extensions USING btree (number);

CREATE INDEX ix_extensions_tenant_id ON public.extensions USING btree (tenant_id);

CREATE INDEX ix_inbound_routes_tenant_id ON public.inbound_routes USING btree (tenant_id);

CREATE INDEX ix_licenses_tenant_id ON public.licenses USING btree (tenant_id);

CREATE INDEX ix_outbound_routes_tenant_id ON public.outbound_routes USING btree (tenant_id);

CREATE INDEX ix_payment_promises_phone ON public.payment_promises USING btree (phone);

CREATE INDEX ix_payment_promises_tenant_id ON public.payment_promises USING btree (tenant_id);

CREATE INDEX ix_queues_tenant_id ON public.queues USING btree (tenant_id);

CREATE UNIQUE INDEX ix_refresh_tokens_token_hash ON public.refresh_tokens USING btree (token_hash);

CREATE INDEX ix_refresh_tokens_user_id ON public.refresh_tokens USING btree (user_id);

CREATE INDEX ix_role_permissions_tenant_id ON public.role_permissions USING btree (tenant_id);

CREATE INDEX ix_security_alerts_created_at ON public.security_alerts USING btree (created_at);

CREATE INDEX ix_security_alerts_tenant_id ON public.security_alerts USING btree (tenant_id);

CREATE INDEX ix_system_settings_tenant_id ON public.system_settings USING btree (tenant_id);

CREATE UNIQUE INDEX ix_tenants_sip_domain ON public.tenants USING btree (sip_domain);

CREATE UNIQUE INDEX ix_tenants_slug ON public.tenants USING btree (slug);

CREATE UNIQUE INDEX ix_tenants_subdomain ON public.tenants USING btree (subdomain);

CREATE INDEX ix_trunks_tenant_id ON public.trunks USING btree (tenant_id);

CREATE INDEX ix_users_tenant_id ON public.users USING btree (tenant_id);

CREATE UNIQUE INDEX ix_users_username ON public.users USING btree (username);

CREATE INDEX ix_voicebots_tenant_id ON public.voicebots USING btree (tenant_id);

CREATE UNIQUE INDEX ux_appointments_tenant_slot ON public.appointments USING btree (tenant_id, appointment_date) WHERE ((status)::text = 'confirmed'::text);

CREATE TRIGGER audit_log_sin_update BEFORE UPDATE ON public.audit_log FOR EACH ROW EXECUTE FUNCTION public.audit_log_inmutable();

ALTER TABLE ONLY public.ai_call_usage
    ADD CONSTRAINT ai_call_usage_appointment_id_fkey FOREIGN KEY (appointment_id) REFERENCES public.appointments(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.ai_call_usage
    ADD CONSTRAINT ai_call_usage_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.appointments
    ADD CONSTRAINT appointments_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.call_logs
    ADD CONSTRAINT call_logs_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.campaigns(id);

ALTER TABLE ONLY public.call_logs
    ADD CONSTRAINT call_logs_extension_id_fkey FOREIGN KEY (extension_id) REFERENCES public.extensions(id);

ALTER TABLE ONLY public.call_logs
    ADD CONSTRAINT call_logs_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.campaign_numbers
    ADD CONSTRAINT campaign_numbers_appointment_id_fkey FOREIGN KEY (appointment_id) REFERENCES public.appointments(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.campaign_numbers
    ADD CONSTRAINT campaign_numbers_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.campaigns(id);

ALTER TABLE ONLY public.campaign_numbers
    ADD CONSTRAINT campaign_numbers_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.campaigns
    ADD CONSTRAINT campaigns_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.campaigns
    ADD CONSTRAINT campaigns_trunk_id_fkey FOREIGN KEY (trunk_id) REFERENCES public.trunks(id);

ALTER TABLE ONLY public.campaigns
    ADD CONSTRAINT campaigns_voicebot_id_fkey FOREIGN KEY (voicebot_id) REFERENCES public.voicebots(id);

ALTER TABLE ONLY public.debts
    ADD CONSTRAINT debts_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.device_tokens
    ADD CONSTRAINT device_tokens_extension_id_fkey FOREIGN KEY (extension_id) REFERENCES public.extensions(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.device_tokens
    ADD CONSTRAINT device_tokens_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.device_tokens
    ADD CONSTRAINT device_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.extensions
    ADD CONSTRAINT extensions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.inbound_routes
    ADD CONSTRAINT inbound_routes_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.licenses
    ADD CONSTRAINT licenses_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.outbound_routes
    ADD CONSTRAINT outbound_routes_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.payment_promises
    ADD CONSTRAINT payment_promises_debt_id_fkey FOREIGN KEY (debt_id) REFERENCES public.debts(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.payment_promises
    ADD CONSTRAINT payment_promises_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.queues
    ADD CONSTRAINT queues_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT refresh_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.security_alerts
    ADD CONSTRAINT security_alerts_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.system_settings
    ADD CONSTRAINT system_settings_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.system_settings
    ADD CONSTRAINT system_settings_webcall_queue_id_fkey FOREIGN KEY (webcall_queue_id) REFERENCES public.queues(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.trunks
    ADD CONSTRAINT trunks_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_extension_id_fkey FOREIGN KEY (extension_id) REFERENCES public.extensions(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.voicebots
    ADD CONSTRAINT voicebots_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE public.ai_call_usage ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.appointments ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.audit_log ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.call_logs ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.campaign_numbers ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.campaigns ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.debts ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.device_tokens ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.extensions ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.inbound_routes ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.licenses ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.outbound_routes ENABLE ROW LEVEL SECURITY;

CREATE POLICY p_tenant ON public.ai_call_usage USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer)) WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer));

CREATE POLICY p_tenant ON public.appointments USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer)) WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer));

CREATE POLICY p_tenant ON public.audit_log USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer)) WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer));

CREATE POLICY p_tenant ON public.call_logs USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer)) WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer));

CREATE POLICY p_tenant ON public.campaign_numbers USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer)) WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer));

CREATE POLICY p_tenant ON public.campaigns USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer)) WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer));

CREATE POLICY p_tenant ON public.debts USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer)) WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer));

CREATE POLICY p_tenant ON public.device_tokens USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer)) WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer));

CREATE POLICY p_tenant ON public.extensions USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer)) WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer));

CREATE POLICY p_tenant ON public.inbound_routes USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer)) WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer));

CREATE POLICY p_tenant ON public.licenses USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer)) WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer));

CREATE POLICY p_tenant ON public.outbound_routes USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer)) WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer));

CREATE POLICY p_tenant ON public.payment_promises USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer)) WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer));

CREATE POLICY p_tenant ON public.queues USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer)) WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer));

CREATE POLICY p_tenant ON public.role_permissions USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer)) WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer));

CREATE POLICY p_tenant ON public.security_alerts USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer)) WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer));

CREATE POLICY p_tenant ON public.system_settings USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer)) WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer));

CREATE POLICY p_tenant ON public.trunks USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer)) WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer));

CREATE POLICY p_tenant ON public.users USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer)) WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer));

CREATE POLICY p_tenant ON public.voicebots USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer)) WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::integer));

ALTER TABLE public.payment_promises ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.queues ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.role_permissions ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.security_alerts ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.system_settings ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.trunks ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.voicebots ENABLE ROW LEVEL SECURITY;

