import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .routes.resumes import router as resume_router

app = FastAPI(title="CampusConnect AI Resume Analyzer", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(resume_router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError):
    fields = [{"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"]} for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": {"code": "validation_error", "message": "The request fields are invalid.", "fields": fields}})
