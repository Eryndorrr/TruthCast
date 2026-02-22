"""
应对内容生成 API 路由

提供：
- POST /content/generate - 生成完整应对内容
- POST /content/clarification - 仅生成澄清稿
- POST /content/faq - 仅生成FAQ
- POST /content/platform-scripts - 仅生成多平台话术
"""

from fastapi import APIRouter

from app.schemas.detect import (
    ContentGenerateRequest,
    ContentGenerateResponse,
    ClarificationContent,
    FAQItem,
    PlatformScript,
)
from app.services.content_generation import (
    generate_full_content,
    generate_clarification_only,
    generate_faq_only,
    generate_platform_scripts_only,
)

router = APIRouter(prefix="/content", tags=["content"])


@router.post("/generate", response_model=ContentGenerateResponse)
async def generate_content(request: ContentGenerateRequest):
    """
    生成完整应对内容
    
    - 澄清稿（短/中/长三版）
    - FAQ（可选）
    - 多平台话术
    """
    return await generate_full_content(request)


@router.post("/clarification", response_model=ClarificationContent)
async def generate_clarification(request: ContentGenerateRequest):
    """仅生成澄清稿"""
    return await generate_clarification_only(request)


@router.post("/faq", response_model=list[FAQItem])
async def generate_faq(request: ContentGenerateRequest):
    """仅生成FAQ"""
    return await generate_faq_only(request)


@router.post("/platform-scripts", response_model=list[PlatformScript])
async def generate_platform_scripts(request: ContentGenerateRequest):
    """仅生成多平台话术"""
    return await generate_platform_scripts_only(request)
