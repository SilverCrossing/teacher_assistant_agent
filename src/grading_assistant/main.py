import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from decimal import Decimal
from urllib.parse import quote, unquote

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings, data_dir, load_settings
from .contracts import CreateRun, ReviewInput
from .grading import DomainError
from .model_settings import ModelSettingsInput, ModelSettingsService
from .orchestrator import Orchestrator
from .storage import Store, load_cipher
from .materials import MaterialLibrary, ExamInput, ExamEdit, MAX_FILE
from .simulation import SimulationService, SimulationStart, SimulationDraft, SimulationReview


def create_app(settings: Settings | None = None, directory: Path | None = None) -> FastAPI:
    settings = settings or load_settings()
    directory = directory or data_dir()
    token = secrets.token_urlsafe(32)
    materials = MaterialLibrary(directory)
    simulation = SimulationService(materials)
    # 本地连接参数独立保存，不改写学校授权配置或把密钥写进 JSON。
    model_settings = ModelSettingsService(settings, directory)
    settings.cloud = model_settings.effective()

    @asynccontextmanager
    async def lifespan(app):
        directory.mkdir(parents=True, exist_ok=True)
        lock = open(directory / "instance.lock", "a+b")
        lock.seek(0)
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock.close()
            raise RuntimeError("ANOTHER_INSTANCE_RUNNING") from None
        store = None
        try:
            cipher = load_cipher(directory, settings.site.enabled)
            store = Store(directory / ("school.db" if settings.site.enabled else "synthetic.db"), cipher)
            store.purge(settings.retention_days)
            store.recover()
            app.state.agent = Orchestrator(settings, store)
            yield
        finally:
            if hasattr(app.state, "agent"):
                await app.state.agent.shutdown()
            if store:
                store.close()
            lock.close()

    app = FastAPI(title="学校阅卷助手", version="0.1.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    allowed_origins = {"http://127.0.0.1:8765", "http://localhost:8765",
                       "http://127.0.0.1:5173", "http://localhost:5173"}

    @app.middleware("http")
    async def local_security(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            if request.headers.get("origin") and request.headers["origin"] not in allowed_origins:
                return JSONResponse({"code": "ORIGIN_DENIED"}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"code": "ORIGIN_DENIED"}, status_code=403)
            if request.url.path not in {"/api/session", "/api/health"}:
                if not secrets.compare_digest(request.headers.get("x-local-token", ""), token):
                    return JSONResponse({"code": "LOCAL_TOKEN_REQUIRED"}, status_code=401)
            if request.method == "POST":
                # 仅资料接口放宽大小；上传仍校验令牌、来源及实际流长度。
                limit = (MAX_FILE if request.url.path.endswith("/files") and request.url.path.startswith("/api/materials/")
                         else 2_000_000 if request.url.path.startswith("/api/materials/") else 32_000)
                try:
                    if int(request.headers.get("content-length", "0")) > limit:
                        return JSONResponse({"code": "REQUEST_TOO_LARGE"}, status_code=413)
                except ValueError:
                    return JSONResponse({"code": "INVALID_REQUEST"}, status_code=400)
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > limit:
                        return JSONResponse({"code": "REQUEST_TOO_LARGE"}, status_code=413)
                request._body = bytes(body)
        response = await call_next(request)
        response.headers.update({
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                       "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
        })
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        status = 404 if exc.code.endswith("_NOT_FOUND") else 409
        return JSONResponse({"code": exc.code}, status_code=status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return JSONResponse({"code": "INVALID_REQUEST"}, status_code=422)

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        # 对外仅返回错误码，避免回显网页正文、凭据、模型响应或教师备注。
        return JSONResponse({"code": "INTERNAL_ERROR"}, status_code=500)

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "schema_version": "1"}

    @app.get("/api/session")
    async def session():
        return {"token": token, "school_enabled": settings.site.enabled,
                "cloud_enabled": settings.cloud.enabled, "retention_days": settings.retention_days,
                "cloud_model": settings.cloud.model, "cloud_region": settings.cloud.region,
                "cloud_endpoint": settings.cloud.endpoint,
                "cloud_retention_terms": settings.cloud.retention_terms,
                "cloud_training_terms": settings.cloud.training_terms}

    @app.get("/api/settings/model")
    async def get_model_settings():
        return model_settings.public()

    @app.post("/api/settings/model")
    async def save_model_settings(body: ModelSettingsInput):
        # 连接改变时不允许已有任务继续沿用旧配置和旧的外发确认。
        app.state.agent.idle()
        result = model_settings.save(body)
        settings.cloud = model_settings.effective()
        return result

    @app.post("/api/settings/model/test")
    async def test_model_settings(body: ModelSettingsInput):
        return await model_settings.test(body)

    @app.get("/api/tasks")
    async def tasks():
        return app.state.agent.tasks()

    @app.get("/api/simulations")
    def list_simulations():
        return simulation.list()

    @app.post("/api/simulations", status_code=201)
    def start_simulation(body: SimulationStart):
        return simulation.start(body)

    @app.get("/api/simulations/{session_id}")
    def get_simulation(session_id: str):
        return simulation.get(session_id)

    @app.post("/api/simulations/{session_id}/cards/{card_id}/draft")
    def draft_simulation(session_id: str, card_id: str, body: SimulationDraft):
        return simulation.update(session_id, card_id, body)

    @app.post("/api/simulations/{session_id}/cards/{card_id}/review")
    def review_simulation(session_id: str, card_id: str, body: SimulationReview):
        return simulation.update(session_id, card_id, body, review=True)

    @app.get("/api/materials")
    def list_materials():
        return materials.list()

    @app.post("/api/materials", status_code=201)
    def create_material(body: ExamInput):
        return materials.create(body)

    @app.get("/api/materials/{exam_id}")
    def get_material(exam_id: str):
        return materials.get(exam_id)

    @app.post("/api/materials/{exam_id}")
    def save_material(exam_id: str, body: ExamEdit):
        return materials.save(exam_id, body)

    @app.post("/api/materials/{exam_id}/files")
    async def upload_material(exam_id: str, request: Request):
        try:
            version = int(request.headers.get("x-material-version", ""))
        except ValueError:
            raise DomainError("MATERIAL_FILE_INVALID") from None
        return await run_in_threadpool(
            materials.upload, exam_id, version, request.headers.get("x-material-role", ""),
            unquote(request.headers.get("x-file-name", "")), await request.body())

    @app.get("/api/materials/{exam_id}/files/{file_id}")
    def download_material(exam_id: str, file_id: str):
        meta, raw = materials.download(exam_id, file_id)
        return Response(raw, media_type=meta["mime"],
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(meta['name'])}"})

    @app.get("/api/runs")
    async def runs():
        return [{k: v for k, v in run.items() if k != "items"} | {"count": len(run["items"])}
                for run in app.state.agent.store.list()]

    @app.post("/api/runs", status_code=201)
    async def create_run(body: CreateRun):
        task = None
        if body.material_id:
            from .contracts import GradingTask
            exam = materials.get(body.material_id)
            if not exam["confirmed"] or exam["version"] != body.material_version:
                raise DomainError("MATERIAL_NOT_CONFIRMED")
            question = next((q for q in exam["questions"] if q["number"] == body.material_question), None)
            base = app.state.agent.task(body.task_id)
            if not question or not settings.site.enabled or base.id != settings.site.task.id:
                raise DomainError("MATERIAL_MAPPING_INVALID")
            total = sum(Decimal(str(c["max_score"])) for c in question["criteria"])
            if total != Decimal(str(base.max_score)):
                raise DomainError("MATERIAL_SCORE_MISMATCH")
            # 站点身份仍来自已授权任务；资料仅替换教师确认的题干和量规。
            task = GradingTask.model_validate(base.model_dump() | {
                "question": question["prompt"] + "\n\n【教师确认的参考答案】\n" + question["answer"],
                "criteria": question["criteria"],
                "rubric_version": f"material:{exam['id']}:v{exam['version']}:{question['number']}",
                "title": f"{exam['title']} · {exam['paper']} · {question['number']}",
            })
        return app.state.agent.create(body.task_id, task)

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str):
        return app.state.agent.get(run_id)

    @app.post("/api/runs/{run_id}/confirm-login")
    async def confirm_login(run_id: str):
        return app.state.agent.confirm_login(run_id)

    @app.post("/api/runs/{run_id}/generate")
    async def generate(run_id: str):
        return app.state.agent.generate(run_id)

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel(run_id: str):
        return await app.state.agent.cancel(run_id)

    @app.post("/api/runs/{run_id}/resume")
    async def resume(run_id: str):
        return app.state.agent.resume(run_id)

    @app.post("/api/runs/{run_id}/submissions/{submission_id}/review")
    async def review(run_id: str, submission_id: str, body: ReviewInput):
        return app.state.agent.review(run_id, submission_id, body)

    @app.get("/api/runs/{run_id}/audit")
    async def audit(run_id: str):
        app.state.agent.store.get(run_id)
        return app.state.agent.store.audit(run_id)

    import sys
    # 打包程序从 PyInstaller 的资源目录读取前端；源码运行仍使用原目录。
    dist = (Path(sys._MEIPASS) / "frontend/dist" if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[2] / "frontend/dist")
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        async def index():
            return FileResponse(dist / "index.html")
    else:
        @app.get("/")
        async def not_built():
            return {"message": "请先在 frontend 运行 npm install 和 npm run build，或启动 npm run dev。"}

    return app


def main():
    import uvicorn
    # 浏览器会话和队列由单进程持有，真实任务不能使用热重载或多 worker。
    uvicorn.run(create_app(), host="127.0.0.1", port=8765, access_log=False, log_level="critical")


if __name__ == "__main__":
    main()
