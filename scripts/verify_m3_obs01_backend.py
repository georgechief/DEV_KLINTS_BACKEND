#!/usr/bin/env python3
"""Static gate for PRD-M3-OBS-01 (Grafana + Loki + Alloy).

Phase 1+: compose services, pinned tags, config paths, no Promtail.
Later phases extend nginx / workflow / runbook asserts.
Phase 1-6 static gate: compose through induce prep + employer checklist.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAILED: list[str] = []


def ok(msg: str) -> None:
    print(f"  OK  {msg}")


def bad(msg: str) -> None:
    print(f" FAIL {msg}")
    FAILED.append(msg)


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        bad(f"missing file: {rel}")
        return ""
    return path.read_text(encoding="utf-8")


def main() -> int:
    print("=== M3-OBS-01 backend verification ===\n")

    compose = read("docker-compose.yml")
    if compose:
        for svc in ("loki:", "alloy:", "grafana:"):
            if re.search(rf"^\s*{re.escape(svc)}", compose, re.M):
                ok(f"compose has {svc.rstrip(':')}")
            else:
                bad(f"compose missing service {svc.rstrip(':')}")

        pins = {
            "loki": r"image:\s*grafana/loki:\d+\.\d+\.\d+",
            "alloy": r"image:\s*grafana/alloy:v\d+\.\d+\.\d+",
            "grafana": r"image:\s*grafana/grafana:\d+\.\d+\.\d+",
        }
        for name, pat in pins.items():
            if re.search(pat, compose):
                ok(f"{name} image tag pinned (no :latest)")
            else:
                bad(f"{name} must use pinned grafana/* tag (not :latest)")

        if re.search(r"grafana/(?:loki|alloy|grafana):latest", compose):
            bad("compose must not use :latest for obs images")
        else:
            ok("no obs :latest tags")

        if re.search(r"^\s*promtail\s*:", compose, re.M | re.I) or re.search(
            r"image:\s*.*promtail", compose, re.I
        ):
            bad("Promtail must not appear as a compose service (use Alloy)")
        else:
            ok("no Promtail service in compose")

        if "prometheus:" in compose and "grafana/prometheus" in compose:
            bad("Prometheus not in OBS-01 v1 scope")
        else:
            ok("no Prometheus service (OBS-01 v1)")

        # Host publish of Grafana/Loki forbidden in v1 (ops via nginx later)
        grafana_block = ""
        m = re.search(r"^\s*grafana:\n(.*?)(?=^\s*\w|\Z)", compose, re.M | re.S)
        if m:
            grafana_block = m.group(1)
        if re.search(r'^\s*-\s*"3000:3000"', grafana_block, re.M):
            bad("grafana must not publish 3000:3000 on host (use nginx path)")
        else:
            ok("grafana not published on host :3000")

        if "/var/run/docker.sock:/var/run/docker.sock:ro" in compose:
            ok("alloy docker.sock mounted read-only")
        else:
            bad("alloy should mount docker.sock :ro")

        for vol in ("loki_data:", "alloy_data:", "grafana_data:"):
            if vol in compose:
                ok(f"volume {vol.rstrip(':')}")
            else:
                bad(f"missing volume {vol.rstrip(':')}")

    loki_cfg = read("deploy/loki/loki-config.yml")
    if loki_cfg:
        if "retention_period:" in loki_cfg and "retention_enabled: true" in loki_cfg:
            ok("loki retention configured")
        else:
            bad("loki-config must enable retention")
        if "filesystem" in loki_cfg:
            ok("loki filesystem storage")
        else:
            bad("loki must use filesystem storage for v1")
        if "http_listen_address: 0.0.0.0" in loki_cfg or "http_listen_address: '0.0.0.0'" in loki_cfg:
            ok("loki listens on 0.0.0.0 (reachable from alloy/grafana)")
        else:
            bad("loki-config must set server.http_listen_address: 0.0.0.0")

    alloy_cfg = read("deploy/alloy/config.alloy")
    if alloy_cfg:
        if "discovery.docker" in alloy_cfg and "loki.write" in alloy_cfg:
            ok("alloy docker discovery -> loki.write")
        else:
            bad("alloy config missing docker discovery or loki.write")
        if 'target_label  = "service"' in alloy_cfg or 'target_label = "service"' in alloy_cfg:
            ok("alloy sets service label")
        else:
            bad("alloy must set service label for Explore filters")
        if 'action        = "keep"' in alloy_cfg or 'action = "keep"' in alloy_cfg:
            ok("alloy keeps compose-project containers only")
        else:
            bad("alloy should keep only compose-labeled containers")
        if "promtail" in alloy_cfg.lower():
            bad("alloy config must not reference promtail")
        else:
            ok("alloy config has no promtail")

    ds = read("deploy/grafana/provisioning/datasources/loki.yml")
    if ds:
        if "type: loki" in ds and "http://loki:3100" in ds:
            ok("grafana Loki datasource provisioned")
        else:
            bad("grafana datasource must point at http://loki:3100")
        if "uid: loki" in ds and "isDefault: true" in ds:
            ok("Phase 2: Loki datasource uid + default for Explore")
        else:
            bad("Phase 2: Loki datasource needs uid: loki and isDefault: true")

    # Phase 2 — required app service labels for Explore / alerts
    required_services = (
        "web",
        "celery_worker",
        "celery_beat",
        "nginx",
        "redis",
    )
    if compose:
        for svc in required_services:
            # Each service block should set klints.obs.service: <name>
            pat = rf"^\s*{re.escape(svc)}:\n(?:.*\n)*?\s+klints\.obs\.service:\s*{re.escape(svc)}\b"
            if re.search(pat, compose, re.M):
                ok(f"Phase 2: compose label klints.obs.service={svc}")
            else:
                bad(f"Phase 2: missing klints.obs.service={svc} on compose service {svc}")

    if alloy_cfg:
        if "klints_obs_service" in alloy_cfg or "label_klints_obs_service" in alloy_cfg:
            ok("Phase 2: alloy maps klints.obs.service -> service")
        else:
            bad("Phase 2: alloy must relabel klints.obs.service to service")

    dash_prov = read("deploy/grafana/provisioning/dashboards/dashboards.yml")
    dash_json = read(
        "deploy/grafana/provisioning/dashboards/json/staging-docker-logs.json"
    )
    if dash_prov and "m3-obs-01" in dash_prov and "path: /etc/grafana/provisioning/dashboards/json" in dash_prov:
        ok("Phase 2: dashboard provider points at json folder")
    else:
        bad("Phase 2: dashboards.yml must provide M3 OBS-01 json path")
    if dash_json and "{service=~\\\"$service\\\"}" in dash_json.replace("\\", ""):
        # JSON has "{service=~\"$service\"}"
        pass
    if dash_json and "$service" in dash_json and (
        "label_values(service)" in dash_json or '"label": "service"' in dash_json
    ):
        ok("Phase 2: Staging Docker Logs dashboard has service variable")
    else:
        bad("Phase 2: staging-docker-logs.json must query label_values(service)")
    if dash_json:
        for svc in required_services:
            if svc not in dash_json:
                bad(f"Phase 2: dashboard allValue/docs missing required service {svc}")
                break
        else:
            ok("Phase 2: dashboard covers five required app services")
    if alloy_cfg:
        if "relabel_rules" in alloy_cfg and "discovery.relabel.containers.rules" in alloy_cfg:
            ok("Phase 2: alloy applies relabel_rules on loki.source.docker (labels on logs)")
        else:
            bad("Phase 2: alloy loki.source.docker must use discovery.relabel.containers.rules")
    if dash_json and "m3-obs-staging-docker-logs" in dash_json:
        ok("Phase 2: dashboard uid m3-obs-staging-docker-logs")
    else:
        bad("Phase 2: dashboard uid missing")

    env_ex = read(".env.example")
    if env_ex:
        for key in (
            "GF_SECURITY_ADMIN_USER",
            "GF_SECURITY_ADMIN_PASSWORD",
            "GF_SERVER_ROOT_URL",
        ):
            if key in env_ex:
                ok(f".env.example documents {key}")
            else:
                bad(f".env.example missing {key}")

    # Phase 3+ placeholders (warn only until implemented)
    nginx = read("deploy/nginx/klints.conf")
    if nginx:
        if "location /grafana/" in nginx and "klints_grafana" in nginx:
            ok("Phase 3: nginx proxies /grafana/ to grafana upstream")
        else:
            bad("Phase 3: nginx must have location /grafana/ -> klints_grafana")
        if "location /health/" in nginx:
            ok("Phase 3: /health/ location preserved")
        else:
            bad("Phase 3: /health/ must remain in nginx config")
        if "X-Forwarded-Proto" in nginx and "Upgrade" in nginx:
            ok("Phase 3: grafana proxy has Forwarded-Proto + websocket Upgrade")
        else:
            bad("Phase 3: grafana location needs X-Forwarded-Proto and Upgrade headers")
        if "location = /grafana" in nginx:
            ok("Phase 3: /grafana redirects to /grafana/")
        else:
            bad("Phase 3: add exact redirect location = /grafana")

    if compose:
        if re.search(
            r"GF_AUTH_ANONYMOUS_ENABLED:\s*[\"']?false",
            compose,
        ) or 'GF_AUTH_ANONYMOUS_ENABLED: "false"' in compose:
            ok("Phase 3: Grafana anonymous auth disabled")
        else:
            bad("Phase 3: GF_AUTH_ANONYMOUS_ENABLED must be false")
        if "GF_SERVER_SERVE_FROM_SUB_PATH" in compose and "/grafana/" in compose:
            ok("Phase 3: Grafana subpath root URL configured")
        else:
            bad("Phase 3: GF_SERVER_ROOT_URL / SERVE_FROM_SUB_PATH required")
        # nginx must wait for grafana (top-level service block)
        if re.search(
            r"(?ms)^\s*nginx:\n(?:.*?\n)*?\s*depends_on:\n(?:.*?\n)*?\s+grafana:\n",
            compose,
        ):
            ok("Phase 3: nginx depends_on grafana")
        else:
            bad("Phase 3: nginx should depend_on grafana")

    # Phase 4 — dashboards + alerts + mailer bridge
    errors_dash = read(
        "deploy/grafana/provisioning/dashboards/json/staging-errors.json"
    )
    if errors_dash and "m3-obs-staging-errors" in errors_dash:
        ok("Phase 4: Staging Errors dashboard provisioned")
    else:
        bad("Phase 4: staging-errors.json with uid m3-obs-staging-errors required")
    if errors_dash and "(?i)error|exception|traceback|critical|fatal" in errors_dash:
        ok("Phase 4: Errors dashboard filters ERROR-like lines")
    else:
        bad("Phase 4: Errors dashboard must filter ERROR-like LogQL")

    contact = read("deploy/grafana/provisioning/alerting/contact-points.yml")
    if (
        contact
        and "m3-obs-noreplyklints" in contact
        and "obs_alert_mailer:8080/alert" in contact
    ):
        ok("Phase 4: contact point m3-obs-noreplyklints -> mailer bridge")
    else:
        bad("Phase 4: contact-points.yml must webhook to obs_alert_mailer")

    policies = read("deploy/grafana/provisioning/alerting/policies.yml")
    if policies and "m3-obs-noreplyklints" in policies and "service" in policies:
        ok("Phase 4: notification policy groups by service")
    else:
        bad("Phase 4: policies.yml must route to contact point and group by service")

    rules = read("deploy/grafana/provisioning/alerting/rules.yml")
    for svc in ("web", "celery_worker", "celery_beat", "nginx", "redis"):
        uid = f"staging-logs-error-{svc}"
        if rules and uid in rules and f'service="{svc}"' in rules:
            ok(f"Phase 4: alert rule {uid}")
        else:
            bad(f"Phase 4: separate alert rule missing for {svc}")
    if rules and 'service=~"' in rules:
        bad("Phase 4: rules must not use a combined service=~ filter")
    elif rules:
        ok("Phase 4: no combined multi-service LogQL alert")
    if rules and rules.count("notification_settings:") >= 5:
        ok("Phase 4: each rule wires notification_settings receiver")
    else:
        bad("Phase 4: all five rules need notification_settings")
    if rules and "replaceNN" in rules and rules.count("m3_obs:") >= 5:
        ok("Phase 4: reduce replaceNN + m3_obs silence label on rules")
    else:
        bad("Phase 4: rules need reduce replaceNN and m3_obs labels")

    bridge = read("deploy/grafana/alert-mailer-bridge/server.py")
    if (
        bridge
        and "MAILER_API_URL" in bridge
        and "noreplyklints@gmail.com" in bridge
        and "urlparse" in bridge
    ):
        ok("Phase 4: alert-mailer-bridge maps webhook -> MAILER_API_*")
    else:
        bad("Phase 4: alert-mailer-bridge/server.py required (urlparse path)")

    if compose and "obs_alert_mailer:" in compose:
        ok("Phase 4: compose has obs_alert_mailer")
        mailer_block = ""
        m_mailer = re.search(
            r"(?ms)^  obs_alert_mailer:\n(.*?)(?=^  \w|\Z)",
            compose,
        )
        if m_mailer:
            mailer_block = m_mailer.group(1)
        if re.search(r"(?m)^\s+ports:\s*$", mailer_block):
            bad("Phase 4: obs_alert_mailer must not publish host ports")
        else:
            ok("Phase 4: obs_alert_mailer not published on host")
        if re.search(r"(?m)^\s+env_file:\s*\.env\s*$", mailer_block) or (
            "env_file: .env" in mailer_block
        ):
            ok("Phase 4: obs_alert_mailer loads MAILER_* via env_file")
        else:
            bad("Phase 4: obs_alert_mailer should use env_file: .env for MAILER_*")
    else:
        bad("Phase 4: obs_alert_mailer service required in docker-compose.yml")

    if env_ex and "ALERT_EMAIL_TO" in env_ex:
        ok(".env.example documents ALERT_EMAIL_TO")
    else:
        bad(".env.example missing ALERT_EMAIL_TO")

    if errors_dash and '"title": "Errors only"' in errors_dash:
        ok("Phase 4: Errors dashboard title matches PRD (Errors only)")
    else:
        bad("Phase 4: Errors dashboard title should be Errors only")

    phase4_notes = read("docs/sahil/M3_OBS_01_PHASE_4.md")
    if phase4_notes and "Silences" in phase4_notes and "m3_obs=01" in phase4_notes:
        ok("Phase 4: silence/mute during deploy documented")
    else:
        bad("Phase 4: M3_OBS_01_PHASE_4.md must document Silences")
    if phase4_notes and "stop-and-flag" in phase4_notes.lower():
        ok("Phase 4: email stop-and-flag path documented")
    else:
        bad("Phase 4: document stop-and-flag if mailer fails")

    # Phase 5 — workflow smoke + runbook + README
    workflow = read(".github/workflows/deploy-development.yml")
    if workflow and "/health/" in workflow and "Smoke check via HTTPS" in workflow:
        ok("Phase 5: workflow still smokes /health/ (must not regress)")
    else:
        bad("Phase 5: keep HTTPS /health/ smoke before OBS checks")
    if workflow and "/grafana/api/health" in workflow:
        ok("Phase 5: workflow smokes Grafana /grafana/api/health")
    else:
        bad("Phase 5: deploy-development.yml must curl /grafana/api/health")
    if workflow and "database" in workflow and "/grafana/api/health" in workflow:
        ok("Phase 5: Grafana health validates response body")
    else:
        bad("Phase 5: Grafana smoke must grep health JSON (not status alone)")
    if workflow and "/grafana/login" in workflow and "login|sign in|password" in workflow:
        ok("Phase 5: workflow checks Grafana login page markers")
    else:
        bad("Phase 5: workflow must curl /grafana/login and assert login markers")
    if workflow and "/grafana/explore" in workflow:
        ok("Phase 5: workflow checks Explore is not anonymously open")
    else:
        bad("Phase 5: workflow should probe /grafana/explore without session")
    if (workflow and "loki:3100" in workflow) or (
        workflow and "m3-obs-loki-ready.sh" in workflow
    ):
        ok("Phase 5: workflow checks Loki /ready")
    else:
        bad("Phase 5: workflow must probe Loki /ready inside compose")
    if (workflow and "m3-obs-loki-ready.sh" in workflow) or (
        workflow and "urllib.request" in workflow and "loki:3100" in workflow
    ):
        ok("Phase 5: Loki probe prefers web Python (reliable tools)")
    else:
        bad("Phase 5: Loki /ready should use web python urllib fallback path")
    if workflow and "Loki not ready yet" in workflow and "seq 1 24" in workflow:
        ok("Phase 5: Loki /ready is retried (503 until ring ACTIVE)")
    else:
        bad("Phase 5: Loki /ready must retry — single-shot fails on cold start 503")
    ready_sh = read("deploy/scripts/m3-obs-loki-ready.sh")
    if ready_sh and "loki:3100" in ready_sh and "/ready" in ready_sh:
        ok("Phase 5: m3-obs-loki-ready.sh probes Loki from web container")
    else:
        bad("Phase 5: deploy/scripts/m3-obs-loki-ready.sh missing or incomplete")
    if workflow and "M3-OBS-01 smoke" in workflow:
        ok("Phase 5: workflow has dedicated M3-OBS-01 smoke step")
    else:
        bad("Phase 5: name/label M3-OBS-01 smoke step in workflow")
    # Ordering: /health/ smoke step name should appear before OBS smoke name
    if workflow:
        i_health = workflow.find("Smoke check via HTTPS domain")
        i_obs = workflow.find("M3-OBS-01 smoke (Grafana via nginx + Loki ready)")
        if i_health >= 0 and i_obs > i_health:
            ok("Phase 5: /health/ smoke runs before OBS smoke")
        else:
            bad("Phase 5: OBS smoke must run after /health/ smoke step")

    runbook = read("docs/sahil/M3_OBS_01_RUNBOOK.md")
    if runbook and "apis.klints.io/grafana/" in runbook:
        ok("Phase 5: runbook has Grafana URL")
    else:
        bad("Phase 5: M3_OBS_01_RUNBOOK.md must document Grafana URL")
    if runbook and "noreplyklints@gmail.com" in runbook and "Explore" in runbook:
        ok("Phase 5: runbook covers login + Explore")
    else:
        bad("Phase 5: runbook must cover login and Explore")
    if runbook and "Silences" in runbook and "m3_obs=01" in runbook:
        ok("Phase 5: runbook covers alert silence")
    else:
        bad("Phase 5: runbook must document Silences")
    if runbook and "deploy-development.yml" in runbook:
        ok("Phase 5: runbook documents deploy workflow")
    else:
        bad("Phase 5: runbook must reference deploy-development.yml")
    missing_fail = [
        n
        for n in ("disk", "docker.sock", "subpath", "MAILER", "SMTP")
        if not runbook or n.lower() not in runbook.lower()
    ]
    if missing_fail:
        bad(f"Phase 5: runbook common-failures missing {missing_fail}")
    else:
        ok("Phase 5: runbook covers common failures")
    if runbook and "SEC-01" in runbook and "Prometheus" in runbook and "Promtail" in runbook:
        ok("Phase 5: runbook states what OBS-01 is not")
    else:
        bad("Phase 5: runbook must disclaim SEC-01 / Prometheus / Promtail")
    if runbook and "product ui" in runbook.lower():
        ok("Phase 5: runbook forbids product UI Grafana link")
    else:
        bad("Phase 5: runbook must say no product UI link")

    readme = read("docs/sahil/README.md")
    if (
        readme
        and "PRD_M3_OBS_01" in readme
        and "M3_OBS_01_RUNBOOK.md" in readme
        and "PHASE_5" in readme
    ):
        ok("Phase 5: README build-order links runbook + Phase 5")
    else:
        bad("Phase 5: docs/sahil/README.md must link RUNBOOK and PHASE_5")

    phase5_notes = read("docs/sahil/M3_OBS_01_PHASE_5.md")
    if phase5_notes and "grafana/api/health" in phase5_notes and "Explore" in phase5_notes:
        ok("Phase 5: phase notes present")
    else:
        bad("Phase 5: M3_OBS_01_PHASE_5.md required (document hardened smoke)")

    # Phase 6 — induce prep + employer checklist (live deploy is post-merge)
    marker_mod = read("core/m3_obs.py")
    if marker_mod and "M3-OBS-01-INDUCE-WEB" in marker_mod:
        ok("Phase 6: shared INDUCE_MARKER constant present")
    else:
        bad("Phase 6: core/m3_obs.py must define M3-OBS-01-INDUCE-WEB")
    induce_cmd = read("core/management/commands/m3_obs_induce_error.py")
    if induce_cmd and "INDUCE_MARKER" in induce_cmd and "urllib.request" in induce_cmd:
        ok("Phase 6: m3_obs_induce_error POSTs to live web (Alloy-visible)")
    else:
        bad("Phase 6: induce command must POST to running web (not exec-only logger)")
    if induce_cmd and "--yes" in induce_cmd:
        ok("Phase 6: induce requires --yes confirmation")
    else:
        bad("Phase 6: induce command must require --yes")
    if induce_cmd and "M3_OBS_INDUCE_ENABLED" in induce_cmd:
        ok("Phase 6: induce command checks M3_OBS_INDUCE_ENABLED")
    else:
        bad("Phase 6: induce command must require M3_OBS_INDUCE_ENABLED")

    views = read("core/views.py")
    urls = read("core/urls.py")
    if (
        views
        and "M3ObsInduceErrorView" in views
        and "INDUCE_MARKER" in views
        and "compare_digest" in views
    ):
        ok("Phase 6: gated induce view with token compare")
    else:
        bad("Phase 6: M3ObsInduceErrorView with secrets.compare_digest required")
    if urls and "ops/m3-obs-01/induce-error/" in urls:
        ok("Phase 6: induce URL wired")
    else:
        bad("Phase 6: urls must include ops/m3-obs-01/induce-error/")

    settings_base = read("core/settings/base.py")
    if (
        settings_base
        and "M3_OBS_INDUCE_ENABLED" in settings_base
        and 'default=False' in settings_base[settings_base.find("M3_OBS_INDUCE_ENABLED") : settings_base.find("M3_OBS_INDUCE_ENABLED") + 120]
    ):
        ok("Phase 6: M3_OBS_INDUCE_ENABLED defaults false")
    else:
        bad("Phase 6: settings must define M3_OBS_INDUCE_ENABLED default False")

    induce_sh = read("deploy/scripts/m3-obs-induce-web-error.sh")
    if induce_sh and "m3_obs_induce_error" in induce_sh and "json-file" in induce_sh:
        ok("Phase 6: droplet induce script documents Docker log path")
    else:
        bad("Phase 6: deploy/scripts/m3-obs-induce-web-error.sh required")

    if env_ex and "M3_OBS_INDUCE_ENABLED" in env_ex and "M3_OBS_INDUCE_TOKEN" in env_ex:
        ok("Phase 6: .env.example documents induce flags")
    else:
        bad("Phase 6: .env.example must document M3_OBS_INDUCE_*")

    phase6 = read("docs/sahil/M3_OBS_01_PHASE_6.md")
    if phase6 and "M3-OBS-01-INDUCE-WEB" in phase6:
        ok("Phase 6: phase notes document induce marker")
    else:
        bad("Phase 6: M3_OBS_01_PHASE_6.md required")
    missing_a = [
        item
        for item in ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10")
        if not phase6 or f"**{item}**" not in phase6
    ]
    if missing_a:
        bad(f"Phase 6: employer checklist missing {missing_a}")
    else:
        ok("Phase 6: employer section 11 checklist template complete")
    if phase6 and "redis" in phase6.lower() and "false" in phase6.lower():
        ok("Phase 6: false-fire check documented")
    else:
        bad("Phase 6: document redis/other false-fire confirmation")

    if runbook and "M3-OBS-01-INDUCE-WEB" in runbook and "Phase 6" in runbook:
        ok("Phase 6: runbook covers induce acceptance steps")
    else:
        bad("Phase 6: RUNBOOK must include Phase 6 induce steps")

    if readme and "PHASE_6" in readme:
        ok("Phase 6: README links PHASE_6")
    else:
        bad("Phase 6: docs/sahil/README.md must link PHASE_6")

    print()
    if FAILED:
        print(f"FAILED ({len(FAILED)}):")
        for item in FAILED:
            print(f"  - {item}")
        return 1
    print("M3-OBS-01 Phase 1-6 static checks: PASS")
    print(
        "NOTE: Phase 6 live deploy/observe/sign-off happens after PR merge "
        "(see docs/sahil/M3_OBS_01_PHASE_6.md)."
    )
    return 0



if __name__ == "__main__":
    sys.exit(main())