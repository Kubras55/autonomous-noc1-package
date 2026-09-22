--
-- PostgreSQL database dump
--

\restrict doYqwsKzVxYK3W2lpUXXoEmgT24mPP2OxIZ9SZbsZOstWTh8YDa7uPry6YvAx8S

-- Dumped from database version 16.14
-- Dumped by pg_dump version 16.14

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

--
-- Name: incidentstatus; Type: TYPE; Schema: public; Owner: noc
--

CREATE TYPE public.incidentstatus AS ENUM (
    'open',
    'investigating',
    'resolved',
    'closed'
);


ALTER TYPE public.incidentstatus OWNER TO noc;

--
-- Name: severity; Type: TYPE; Schema: public; Owner: noc
--

CREATE TYPE public.severity AS ENUM (
    'low',
    'medium',
    'high',
    'critical'
);


ALTER TYPE public.severity OWNER TO noc;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: incidents; Type: TABLE; Schema: public; Owner: noc
--

CREATE TABLE public.incidents (
    id character varying(36) NOT NULL,
    title character varying(200) NOT NULL,
    description text NOT NULL,
    severity public.severity NOT NULL,
    source character varying(100) NOT NULL,
    affected_service character varying(100) NOT NULL,
    status public.incidentstatus NOT NULL,
    fingerprint character varying(255),
    root_cause text,
    confidence_score double precision,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.incidents OWNER TO noc;

--
-- Data for Name: incidents; Type: TABLE DATA; Schema: public; Owner: noc
--

COPY public.incidents (id, title, description, severity, source, affected_service, status, fingerprint, root_cause, confidence_score, created_at, updated_at) FROM stdin;
418a7db0-988d-478c-9766-4bfd607a48ef	VLAN 100 access error	BNG dot1q mismatch	high	lab-r3	subscriber-vlan-100	open	\N	VLAN/802.1Q yapılandırma uyuşmazlığı	0.92	2026-08-04 04:33:39.098108+00	2026-08-04 04:33:39.130522+00
fef4cf87-313a-4b20-ac60-7f9dcf24ba8d	R2-EDGE GNS3 node is stopped	GNS3 monitor detected that R2-EDGE status is stopped	critical	gns3-monitor	R2-EDGE	open	\N	GNS3 ağ düğümü durdurulmuş veya emülatör süreci çalışmıyor	0.98	2026-08-04 11:33:58.948224+00	2026-08-04 11:36:21.162725+00
bf1bb369-033c-4914-adac-3860f13cfe4f	R1-CORE is down in GNS3	GNS3 node is stopped or unavailable. API alarm status: firing.	critical	gns3	R1-CORE	open	gns3-node-down:Autonomous-NOC-GNS3:R1-CORE	\N	\N	2026-08-10 10:38:31.878492+00	2026-08-10 10:38:31.87852+00
6dad1fad-9c91-4655-8349-929c0d8820a6	R2-EDGE is down in GNS3	GNS3 node is stopped or unavailable. API alarm status: firing.	critical	prometheus	R2-EDGE	open	gns3-node-down:Autonomous-NOC-GNS3:R2-EDGE	GNS3 ağ düğümü durdurulmuş veya emülatör süreci çalışmıyor	0.98	2026-08-10 06:05:33.471357+00	2026-08-10 10:38:32.031361+00
285545f3-54c6-41d9-9072-9dd64f53b19e	R3-BNG is down in GNS3	GNS3 node is stopped or unavailable. API alarm status: firing.	critical	gns3	R3-BNG	open	gns3-node-down:Autonomous-NOC-GNS3:R3-BNG	GNS3 ağ düğümü durdurulmuş veya emülatör süreci çalışmıyor	0.98	2026-08-10 10:38:32.054975+00	2026-08-12 10:12:00.750771+00
d11cead2-5adc-4e72-b673-51e8043c8882	API p95 gecikmesi yüksek		high	prometheus	backend	resolved	e27e966034fed356	\N	\N	2026-08-10 08:11:21.887346+00	2026-08-12 10:21:03.592965+00
c37b2508-6d85-4b13-9027-a61dddabfdfc	VLAN 100 access error	BNG dot1q mismatch	high	lab-r3	subscriber-vlan-100	open	\N	BNG dot1q mismatch	0.92	2026-08-04 04:34:25.786159+00	2026-08-18 04:36:36.619741+00
\.


--
-- Name: incidents incidents_fingerprint_key; Type: CONSTRAINT; Schema: public; Owner: noc
--

ALTER TABLE ONLY public.incidents
    ADD CONSTRAINT incidents_fingerprint_key UNIQUE (fingerprint);


--
-- Name: incidents incidents_pkey; Type: CONSTRAINT; Schema: public; Owner: noc
--

ALTER TABLE ONLY public.incidents
    ADD CONSTRAINT incidents_pkey PRIMARY KEY (id);


--
-- PostgreSQL database dump complete
--

\unrestrict doYqwsKzVxYK3W2lpUXXoEmgT24mPP2OxIZ9SZbsZOstWTh8YDa7uPry6YvAx8S

