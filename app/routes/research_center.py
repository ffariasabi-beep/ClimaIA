from concurrent.futures import ThreadPoolExecutor
from collections import Counter

from flask import Blueprint, current_app, jsonify, render_template, request
from flask_login import current_user, login_required

from app.extensions import db
from app.models import AIReport, Investigation
from app.services.research_agent_service import ResearchAgentService


research_center_bp = Blueprint(
    "research_center",
    __name__,
    url_prefix="/research-center"
)

_RESEARCH_EXECUTOR = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="climaia-research"
)


def _serialize_investigation(investigation):
    return {
        "id": investigation.id,
        "title": investigation.title,
        "description": investigation.description or "",
        "status": investigation.status,
        "created_at": investigation.created_at.isoformat(),
        "updated_at": investigation.updated_at.isoformat(),
        "locations": (investigation.parameters or {}).get("locations", [])
    }


def _serialize_report(report):
    evidence = report.input_evidence or {}
    return {
        "id": report.id,
        "status": report.status,
        "question": evidence.get("question", ""),
        "answer": report.generated_content or "",
        "results": evidence.get("results", []),
        "error": evidence.get("error"),
        "created_at": report.created_at.isoformat()
    }


def _previous_conversation(investigation_id, current_report_id):
    reports = (
        AIReport.query
        .filter(
            AIReport.investigation_id == investigation_id,
            AIReport.id != current_report_id,
            AIReport.report_type == "research_turn",
            AIReport.status == "completed"
        )
        .order_by(AIReport.id.desc())
        .limit(6)
        .all()
    )
    messages = []
    for report in reversed(reports):
        question = (report.input_evidence or {}).get("question")
        if question:
            messages.append({"role": "user", "content": question})
        if report.generated_content:
            messages.append({
                "role": "assistant",
                "content": report.generated_content
            })
    return messages



def _run_research_job(app, report_id, investigation_id, user_id):
    with app.app_context():
        try:
            report = db.session.get(AIReport, report_id)
            investigation = db.session.get(Investigation, investigation_id)

            if (
                report is None
                or investigation is None
                or investigation.user_id != user_id
                or report.investigation_id != investigation_id
            ):
                return

            evidence = dict(report.input_evidence or {})
            question = evidence.get("question", "")

            report.status = "processing"
            db.session.commit()

            app.logger.info(
                "[ClimaIA] Iniciando investigación %s: %s",
                report_id,
                question
            )

            history = _previous_conversation(
                investigation_id,
                report_id
            )

            result = ResearchAgentService.run(
                question=question,
                conversation_history=history,
                investigation_id=investigation_id,
                user_id=user_id
            )

            if not isinstance(result, dict):
                raise RuntimeError(
                    "El agente devolvió una respuesta vacía o inválida."
                )

            answer = result.get("answer")
            if not isinstance(answer, str) or not answer.strip():
                raise RuntimeError(
                    "El agente terminó sin generar una respuesta."
                )

            evidence["results"] = result.get("results", [])
            evidence["tool_call_count"] = result.get("tool_call_count", 0)
            evidence["locations_used"] = result.get("locations_used", [])

            report.input_evidence = evidence
            report.generated_content = answer
            report.provider = result.get(
                "provider",
                "Cloudflare Workers AI"
            )
            report.model_name = result.get(
                "model",
                report.model_name
            )
            report.status = "completed"

            parameters = dict(investigation.parameters or {})
            locations = {
                str(item["geoname_id"]): item
                for item in parameters.get("locations", [])
                if item.get("geoname_id") is not None
            }

            for item in result.get("locations_used", []):
                locations[str(item["geoname_id"])] = item

            parameters["locations"] = list(locations.values())
            investigation.parameters = parameters

            if result.get("saved"):
                investigation.status = "saved"

            db.session.commit()

            app.logger.info(
                "[ClimaIA] Investigación %s completada correctamente.",
                report_id
            )

        except Exception as error:
            db.session.rollback()

            app.logger.exception(
                "[ClimaIA] Falló la investigación %s: %s",
                report_id,
                error
            )

            report = db.session.get(AIReport, report_id)

            if report is not None:
                evidence = dict(report.input_evidence or {})
                evidence["error"] = str(error)

                report.input_evidence = evidence
                report.status = "error"

                db.session.commit()

        finally:
            db.session.remove()

@research_center_bp.route("/", methods=["GET"])
@login_required
def index():
    investigations = (
        Investigation.query
        .filter_by(
            user_id=current_user.id,
            investigation_type="climate_research"
        )
        .filter(Investigation.status.in_(("saved", "draft")))
        .order_by(Investigation.updated_at.desc())
        .limit(20)
        .all()
    )
    saved_investigations = (
        Investigation.query
        .filter_by(
            user_id=current_user.id,
            investigation_type="climate_research",
            status="saved"
        )
        .order_by(Investigation.updated_at.desc())
        .limit(20)
        .all()
    )
    saved_count = Investigation.query.filter_by(
        user_id=current_user.id,
        investigation_type="climate_research",
        status="saved"
    ).count()

    locality_counts = Counter()
    locality_labels = {}
    for investigation in saved_investigations:
        for location in (investigation.parameters or {}).get("locations", []):
            geoname_id = location.get("geoname_id")
            if geoname_id is None:
                continue
            locality_counts[str(geoname_id)] += 1
            locality_labels[str(geoname_id)] = (
                location.get("name")
                or location.get("country_name")
                or "Localidad"
            )

    popular_locations = [
        {
            "name": locality_labels[geoname_id],
            "count": count
        }
        for geoname_id, count in locality_counts.most_common(5)
    ]

    return render_template(
        "research_center.html",
        user=current_user,
        investigations=investigations,
        investigation_count=saved_count,
        locality_count=len(locality_counts),
        popular_locations=popular_locations
    )


@research_center_bp.route("/api/messages", methods=["POST"])
@login_required
def submit_message():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "success": False,
            "error": "La solicitud debe contener JSON válido."
        }), 400

    question = payload.get("question")
    if not isinstance(question, str) or not question.strip():
        return jsonify({
            "success": False,
            "error": "Escribí una pregunta de investigación."
        }), 400
    question = question.strip()
    if len(question) > 1200:
        return jsonify({
            "success": False,
            "error": "La pregunta no puede superar los 1200 caracteres."
        }), 400

    investigation_id = payload.get("investigation_id")
    if investigation_id in (None, ""):
        investigation = Investigation(
            user_id=current_user.id,
            title=question[:180],
            description=question[:2000],
            investigation_type="climate_research",
            status="draft",
            parameters={}
        )
        db.session.add(investigation)
        db.session.flush()
    else:
        try:
            investigation_id = int(investigation_id)
        except (TypeError, ValueError):
            return jsonify({
                "success": False,
                "error": "La investigación seleccionada no es válida."
            }), 400
        investigation = Investigation.query.filter_by(
            id=investigation_id,
            user_id=current_user.id,
            investigation_type="climate_research"
        ).first()
        if investigation is None:
            return jsonify({
                "success": False,
                "error": "No se encontró la investigación solicitada."
            }), 404

    pending = AIReport.query.filter(
        AIReport.investigation_id == investigation.id,
        AIReport.report_type == "research_turn",
        AIReport.status.in_(("queued", "processing"))
    ).first()
    if pending is not None:
        db.session.rollback()
        return jsonify({
            "success": False,
            "error": "Esta investigación todavía está procesando otra pregunta."
        }), 409

    report = AIReport(
        investigation_id=investigation.id,
        provider="Cloudflare Workers AI",
        model_name=current_app.config.get("CLOUDFLARE_AI_MODEL"),
        prompt_version="research-agent-v1",
        report_type="research_turn",
        input_evidence={"question": question, "results": []},
        status="queued"
    )
    db.session.add(report)
    db.session.commit()

    app = current_app._get_current_object()
    try:
        _RESEARCH_EXECUTOR.submit(
            _run_research_job,
            app,
            report.id,
            investigation.id,
            current_user.id
        )
    except RuntimeError as error:
        report.status = "error"
        report.input_evidence = {
            "question": question,
            "results": [],
            "error": "No se pudo iniciar el proceso de investigación."
        }
        db.session.commit()
        current_app.logger.exception(
            "No se pudo encolar el trabajo de investigación",
            exc_info=error
        )
        return jsonify({
            "success": False,
            "error": "No se pudo iniciar el proceso de investigación."
        }), 503

    return jsonify({
        "success": True,
        "investigation_id": investigation.id,
        "job_id": report.id,
        "status": report.status
    }), 202


@research_center_bp.route("/api/jobs/<int:report_id>", methods=["GET"])
@login_required
def get_job(report_id):
    report = (
        AIReport.query
        .join(Investigation)
        .filter(
            AIReport.id == report_id,
            Investigation.user_id == current_user.id,
            Investigation.investigation_type == "climate_research",
            AIReport.report_type == "research_turn"
        )
        .first()
    )
    if report is None:
        return jsonify({
            "success": False,
            "error": "No se encontró el proceso de investigación."
        }), 404
    return jsonify({
        "success": True,
        "job": _serialize_report(report)
    })


@research_center_bp.route("/api/history", methods=["GET"])
@login_required
def get_history():
    investigations = (
        Investigation.query
        .filter_by(
            user_id=current_user.id,
            investigation_type="climate_research"
        )
        .filter(Investigation.status.in_(("saved", "draft")))
        .order_by(Investigation.updated_at.desc())
        .limit(30)
        .all()
    )
    return jsonify({
        "success": True,
        "saved_count": Investigation.query.filter_by(
            user_id=current_user.id,
            investigation_type="climate_research",
            status="saved"
        ).count(),
        "investigations": [
            _serialize_investigation(item)
            for item in investigations
        ]
    })


@research_center_bp.route(
    "/api/investigations/<int:investigation_id>",
    methods=["GET"]
)
@login_required
def get_investigation(investigation_id):
    investigation = Investigation.query.filter_by(
        id=investigation_id,
        user_id=current_user.id,
        investigation_type="climate_research"
    ).first()
    if investigation is None:
        return jsonify({
            "success": False,
            "error": "No se encontró la investigación solicitada."
        }), 404

    reports = (
        AIReport.query
        .filter_by(
            investigation_id=investigation.id,
            report_type="research_turn"
        )
        .order_by(AIReport.id.asc())
        .all()
    )
    return jsonify({
        "success": True,
        "investigation": _serialize_investigation(investigation),
        "messages": [_serialize_report(report) for report in reports]
    })


@research_center_bp.route(
    "/api/investigations/<int:investigation_id>/save",
    methods=["POST"]
)
@login_required
def save_investigation(investigation_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "success": False,
            "error": "La solicitud debe contener JSON válido."
        }), 400

    investigation = Investigation.query.filter_by(
        id=investigation_id,
        user_id=current_user.id,
        investigation_type="climate_research"
    ).first()
    if investigation is None:
        return jsonify({
            "success": False,
            "error": "No se encontró la investigación solicitada."
        }), 404

    title = payload.get("title")
    description = payload.get("description", "")
    if not isinstance(title, str) or not title.strip():
        return jsonify({
            "success": False,
            "error": "Ingresá un título para guardar la investigación."
        }), 400
    if len(title.strip()) > 180:
        return jsonify({
            "success": False,
            "error": "El título no puede superar los 180 caracteres."
        }), 400
    if not isinstance(description, str) or len(description) > 2000:
        return jsonify({
            "success": False,
            "error": "La descripción no puede superar los 2000 caracteres."
        }), 400

    has_completed_report = AIReport.query.filter_by(
        investigation_id=investigation.id,
        report_type="research_turn",
        status="completed"
    ).first()
    if has_completed_report is None:
        return jsonify({
            "success": False,
            "error": "Completá una consulta antes de guardar."
        }), 409

    active_job = AIReport.query.filter(
        AIReport.investigation_id == investigation.id,
        AIReport.report_type == "research_turn",
        AIReport.status.in_(("queued", "processing"))
    ).first()
    if active_job is not None:
        return jsonify({
            "success": False,
            "error": "Esperá a que termine la consulta antes de guardar."
        }), 409

    investigation.title = title.strip()
    investigation.description = description.strip() or None
    investigation.status = "saved"
    db.session.commit()
    return jsonify({
        "success": True,
        "investigation": _serialize_investigation(investigation)
    })
