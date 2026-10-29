-- Run with psql as an administrator after the scraper schema is initialized.
-- Required variables: reader_role, database_name, history_schema, scraper_owner.
-- Set the login password separately with psql's interactive \password command.
\set ON_ERROR_STOP on

BEGIN;
CREATE ROLE :"reader_role" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
GRANT CONNECT ON DATABASE :"database_name" TO :"reader_role";
GRANT USAGE ON SCHEMA :"history_schema" TO :"reader_role";
GRANT SELECT ON TABLE
    :"history_schema".matches,
    :"history_schema".bookmaker_listings,
    :"history_schema".scheduled_slots,
    :"history_schema".scraper_runs,
    :"history_schema".bookmaker_outcomes,
    :"history_schema".outcome_odds,
    :"history_schema".missed_slots
TO :"reader_role";
ALTER DEFAULT PRIVILEGES FOR ROLE :"scraper_owner" IN SCHEMA :"history_schema"
    GRANT SELECT ON TABLES TO :"reader_role";
ALTER ROLE :"reader_role" IN DATABASE :"database_name"
    SET default_transaction_read_only = on;
ALTER ROLE :"reader_role" IN DATABASE :"database_name"
    SET search_path TO pg_catalog, :"history_schema";
COMMIT;
