

from fastapi import APIRouter, Depends, Request

from app.api import account, admin, admin_vector, agent, auth, commerce, ingestion, knowledge, merchant, products, search, speech, uploads


api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(account.router)
api_router.include_router(commerce.router)
api_router.include_router(products.router)
api_router.include_router(agent.router)
api_router.include_router(search.router)
api_router.include_router(knowledge.router)
api_router.include_router(ingestion.router)
api_router.include_router(merchant.router)
api_router.include_router(admin.router)
api_router.include_router(admin_vector.router)
api_router.include_router(admin.eval_router)
api_router.include_router(uploads.router)
api_router.include_router(speech.router)


@api_router.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


