import pytest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import AIReport, Investigation, User


@pytest.fixture
def research_client(monkeypatch):
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite://")
    app = create_app()
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False
    )
    with app.app_context():
        db.create_all()
        first_user = User(
            username="researcher-one",
            email="one@example.test",
            password_hash="test-hash"
        )
        second_user = User(
            username="researcher-two",
            email="two@example.test",
            password_hash="test-hash"
        )
        db.session.add_all([first_user, second_user])
        db.session.commit()
        first_user_id = first_user.id
        second_user_id = second_user.id

    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(first_user_id)
        session["_fresh"] = True

    yield client, app, first_user_id, second_user_id

    with app.app_context():
        db.session.remove()
        db.drop_all()


def _create_investigation(user_id, title, status="draft"):
    investigation = Investigation(
        user_id=user_id,
        title=title,
        investigation_type="climate_research",
        status=status,
        parameters={"locations": []}
    )
    db.session.add(investigation)
    db.session.flush()
    return investigation


def test_research_center_lists_only_the_current_users_research(
    research_client
):
    client, app, first_user_id, second_user_id = research_client
    with app.app_context():
        own = _create_investigation(first_user_id, "Borrador propio")
        _create_investigation(second_user_id, "Investigación ajena", "saved")
        db.session.commit()
        own_title = own.title

    response = client.get("/research-center/")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "MÓDULO 01 · MEMORIA CLIMÁTICA" in page
    assert "Borrador propio" in page
    assert own_title in page
    assert "Investigación ajena" not in page
    assert "research_center.js" in page


def test_submitting_a_question_persists_and_queues_it_without_running_ai(
    research_client,
    monkeypatch
):
    client, app, first_user_id, _ = research_client
    from app.routes import research_center as research_routes

    submitted = []

    class DeferredExecutor:
        def submit(self, *args):
            submitted.append(args)

    monkeypatch.setattr(
        research_routes,
        "_RESEARCH_EXECUTOR",
        DeferredExecutor()
    )

    response = client.post(
        "/research-center/api/messages",
        json={"question": "Compará Córdoba con Rosario."}
    )

    assert response.status_code == 202
    assert response.json["success"] is True
    assert len(submitted) == 1
    with app.app_context():
        investigation = db.session.get(
            Investigation,
            response.json["investigation_id"]
        )
        report = db.session.get(AIReport, response.json["job_id"])
        assert investigation.user_id == first_user_id
        assert investigation.status == "draft"
        assert report.status == "queued"
        assert report.provider == "Cloudflare Workers AI"
        assert report.model_name == (
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
        )
        assert report.input_evidence["question"] == (
            "Compará Córdoba con Rosario."
        )


def test_research_job_returns_structured_results_only_to_owner(
    research_client
):
    client, app, first_user_id, second_user_id = research_client
    with app.app_context():
        own = _create_investigation(first_user_id, "Mi análisis", "saved")
        report = AIReport(
            investigation_id=own.id,
            provider="Cloudflare Workers AI",
            report_type="research_turn",
            input_evidence={
                "question": "¿Qué pasó?",
                "results": [{
                    "title": "Temperatura",
                    "chart": {"labels": ["2020"], "datasets": []},
                    "table": {"columns": ["A"], "rows": [[1]]}
                }]
            },
            generated_content="Resumen verificado",
            status="completed"
        )
        db.session.add(report)
        db.session.flush()
        report_id = report.id
        foreign = _create_investigation(second_user_id, "Privada")
        db.session.commit()
        foreign_id = foreign.id

    own_response = client.get(f"/research-center/api/jobs/{report_id}")
    foreign_response = client.get(
        f"/research-center/api/investigations/{foreign_id}"
    )

    assert own_response.status_code == 200
    assert own_response.json["job"]["answer"] == "Resumen verificado"
    assert own_response.json["job"]["results"][0]["chart"]["labels"] == [
        "2020"
    ]
    assert foreign_response.status_code == 404


def test_worker_persists_backend_results_and_locations(
    research_client,
    monkeypatch
):
    _, app, first_user_id, _ = research_client
    from app.routes import research_center as research_routes
    from app.services.research_agent_service import ResearchAgentService

    with app.app_context():
        investigation = _create_investigation(first_user_id, "Serie histórica")
        report = AIReport(
            investigation_id=investigation.id,
            provider="Cloudflare Workers AI",
            report_type="research_turn",
            input_evidence={"question": "Analizá la temperatura.", "results": []},
            status="queued"
        )
        db.session.add(report)
        db.session.commit()
        investigation_id = investigation.id
        report_id = report.id

    monkeypatch.setattr(
        ResearchAgentService,
        "run",
        staticmethod(lambda **kwargs: {
            "answer": "Resultado con evidencia.",
            "results": [{"title": "Temperatura", "chart": {"labels": ["2020"]}}],
            "locations_used": [{
                "geoname_id": 123,
                "name": "Córdoba",
                "country_name": "Argentina"
            }],
            "saved": False,
            "tool_call_count": 2,
            "provider": "Cloudflare Workers AI",
            "model": "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
        })
    )

    research_routes._run_research_job(
        app,
        report_id,
        investigation_id,
        first_user_id
    )

    with app.app_context():
        report = db.session.get(AIReport, report_id)
        investigation = db.session.get(Investigation, investigation_id)
        assert report.status == "completed"
        assert report.provider == "Cloudflare Workers AI"
        assert report.model_name == (
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
        )
        assert report.generated_content == "Resultado con evidencia."
        assert report.input_evidence["results"][0]["chart"]["labels"] == [
            "2020"
        ]
        assert investigation.parameters["locations"][0]["geoname_id"] == 123


def test_saving_requires_a_completed_report_and_is_user_scoped(
    research_client
):
    client, app, first_user_id, second_user_id = research_client
    with app.app_context():
        draft = _create_investigation(first_user_id, "Borrador")
        incomplete = _create_investigation(first_user_id, "Incompleta")
        db.session.add(AIReport(
            investigation_id=draft.id,
            report_type="research_turn",
            input_evidence={"question": "Consulta", "results": []},
            generated_content="Resultado",
            status="completed"
        ))
        other = _create_investigation(second_user_id, "Privada")
        db.session.commit()
        draft_id = draft.id
        incomplete_id = incomplete.id
        other_id = other.id

    incomplete_response = client.post(
        f"/research-center/api/investigations/{incomplete_id}/save",
        json={"title": "Todavía no"}
    )
    saved_response = client.post(
        f"/research-center/api/investigations/{draft_id}/save",
        json={"title": "Análisis guardado", "description": "Notas"}
    )
    foreign_response = client.post(
        f"/research-center/api/investigations/{other_id}/save",
        json={"title": "No autorizado"}
    )

    assert incomplete_response.status_code == 409
    assert saved_response.status_code == 200
    assert saved_response.json["investigation"]["status"] == "saved"
    assert foreign_response.status_code == 404

    with app.app_context():
        saved = db.session.get(Investigation, draft_id)
        assert saved.title == "Análisis guardado"
        assert saved.description == "Notas"
