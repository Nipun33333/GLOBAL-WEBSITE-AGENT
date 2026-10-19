-- Initial immutable PostgreSQL schema. All source, state and evidence are durable.

CREATE TABLE configuration (
	key TEXT NOT NULL, 
	value JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (key)
)

;

CREATE TABLE cost_usage (
	provider TEXT NOT NULL, 
	operation TEXT NOT NULL, 
	key TEXT NOT NULL, 
	reserved_usd FLOAT NOT NULL, 
	actual_usd FLOAT, 
	units JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (key)
)

;

CREATE TABLE country_policies (
	country VARCHAR(2) NOT NULL, 
	policy JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (country)
)

;

CREATE TABLE location_queue (
	country VARCHAR(2) NOT NULL, 
	city TEXT NOT NULL, 
	niche TEXT NOT NULL, 
	last_search TIMESTAMP WITH TIME ZONE, 
	searches INTEGER NOT NULL, 
	relevant INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (country, city, niche)
)

;

CREATE TABLE prospects (
	domain VARCHAR(253) NOT NULL, 
	name TEXT NOT NULL, 
	url TEXT NOT NULL, 
	country VARCHAR(2) NOT NULL, 
	city TEXT NOT NULL, 
	timezone TEXT NOT NULL, 
	language TEXT NOT NULL, 
	subdivision TEXT, 
	niche TEXT NOT NULL, 
	status TEXT NOT NULL, 
	email TEXT, 
	contact_evidence JSON NOT NULL, 
	eligibility JSON NOT NULL, 
	replied_at TIMESTAMP WITH TIME ZONE, 
	imported BOOLEAN NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (domain)
)

;

CREATE TABLE suppressions (
	key TEXT NOT NULL, 
	reason TEXT NOT NULL, 
	evidence TEXT NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (key)
)

;

CREATE TABLE workflow_runs (
	run_key TEXT NOT NULL, 
	kind TEXT NOT NULL, 
	status TEXT NOT NULL, 
	summary JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (run_key)
)

;

CREATE TABLE business_sources (
	prospect_id VARCHAR(36) NOT NULL, 
	provider TEXT NOT NULL, 
	provider_id TEXT NOT NULL, 
	evidence JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (provider, provider_id), 
	FOREIGN KEY(prospect_id) REFERENCES prospects (id)
)

;

CREATE TABLE generated_sites (
	prospect_id VARCHAR(36) NOT NULL, 
	version INTEGER NOT NULL, 
	status TEXT NOT NULL, 
	files JSON NOT NULL, 
	metadata_json JSON NOT NULL, 
	deploy_id TEXT, 
	url TEXT, 
	verified_at TIMESTAMP WITH TIME ZONE, 
	verification JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (prospect_id, version), 
	FOREIGN KEY(prospect_id) REFERENCES prospects (id)
)

;

CREATE TABLE gmail_threads (
	thread_id TEXT NOT NULL, 
	prospect_id VARCHAR(36) NOT NULL, 
	seen_ids JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (thread_id), 
	FOREIGN KEY(prospect_id) REFERENCES prospects (id)
)

;

CREATE TABLE outreach_messages (
	prospect_id VARCHAR(36) NOT NULL, 
	kind TEXT NOT NULL, 
	sequence INTEGER NOT NULL, 
	idempotency_key TEXT NOT NULL, 
	rfc_message_id TEXT NOT NULL, 
	state TEXT NOT NULL, 
	subject TEXT NOT NULL, 
	body TEXT NOT NULL, 
	recipient TEXT NOT NULL, 
	draft_id TEXT, 
	gmail_id TEXT, 
	thread_id TEXT, 
	sent_at TIMESTAMP WITH TIME ZONE, 
	details JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (prospect_id, kind, sequence), 
	FOREIGN KEY(prospect_id) REFERENCES prospects (id), 
	UNIQUE (idempotency_key), 
	UNIQUE (rfc_message_id), 
	UNIQUE (gmail_id)
)

;

CREATE TABLE run_events (
	run_id VARCHAR(36) NOT NULL, 
	event TEXT NOT NULL, 
	details JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(run_id) REFERENCES workflow_runs (id)
)

;

CREATE TABLE website_audits (
	prospect_id VARCHAR(36) NOT NULL, 
	score INTEGER NOT NULL, 
	evidence JSON NOT NULL, 
	research JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (prospect_id), 
	FOREIGN KEY(prospect_id) REFERENCES prospects (id)
)

;

CREATE TABLE followups (
	prospect_id VARCHAR(36) NOT NULL, 
	sequence INTEGER NOT NULL, 
	due_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	message_id VARCHAR(36), 
	status TEXT NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (prospect_id, sequence), 
	FOREIGN KEY(prospect_id) REFERENCES prospects (id), 
	FOREIGN KEY(message_id) REFERENCES outreach_messages (id)
)

;
CREATE INDEX ix_configuration_created_at ON configuration (created_at);
CREATE INDEX ix_cost_usage_created_at ON cost_usage (created_at);
CREATE INDEX ix_country_policies_created_at ON country_policies (created_at);
CREATE INDEX ix_location_queue_country ON location_queue (country);
CREATE INDEX ix_location_queue_created_at ON location_queue (created_at);
CREATE INDEX ix_prospects_status ON prospects (status);
CREATE INDEX ix_prospects_created_at ON prospects (created_at);
CREATE INDEX ix_prospects_email ON prospects (email);
CREATE INDEX ix_suppressions_created_at ON suppressions (created_at);
CREATE INDEX ix_workflow_runs_created_at ON workflow_runs (created_at);
CREATE INDEX ix_business_sources_created_at ON business_sources (created_at);
CREATE INDEX ix_business_sources_prospect_id ON business_sources (prospect_id);
CREATE INDEX ix_generated_sites_created_at ON generated_sites (created_at);
CREATE INDEX ix_generated_sites_prospect_id ON generated_sites (prospect_id);
CREATE INDEX ix_generated_sites_status ON generated_sites (status);
CREATE INDEX ix_gmail_threads_created_at ON gmail_threads (created_at);
CREATE INDEX ix_gmail_threads_prospect_id ON gmail_threads (prospect_id);
CREATE INDEX ix_outreach_messages_thread_id ON outreach_messages (thread_id);
CREATE INDEX ix_outreach_messages_prospect_id ON outreach_messages (prospect_id);
CREATE INDEX ix_outreach_messages_state ON outreach_messages (state);
CREATE INDEX ix_outreach_messages_created_at ON outreach_messages (created_at);
CREATE INDEX ix_run_events_created_at ON run_events (created_at);
CREATE INDEX ix_run_events_run_id ON run_events (run_id);
CREATE INDEX ix_website_audits_created_at ON website_audits (created_at);
CREATE INDEX ix_followups_prospect_id ON followups (prospect_id);
CREATE INDEX ix_followups_created_at ON followups (created_at);