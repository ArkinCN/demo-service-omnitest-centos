"""
AI Model Pricing Configuration

Prices are in CNY (Chinese Yuan) per million tokens.
"""
from typing import Dict, Optional
from dataclasses import dataclass


@dataclass
class ModelPricing:
    """Model pricing configuration"""
    input_price: float      # Input price ¥/M tokens
    output_price: float     # Output price ¥/M tokens
    input_price_large: Optional[float] = None   # Input price for large context
    output_price_large: Optional[float] = None  # Output price for large context
    context_threshold: int = 0  # Context threshold (tokens)
    fixed_price_per_image: Optional[int] = None  # Fixed price per image (0.0001 CNY units)


# Model pricing table (CNY per million tokens)
# Exchange rate reference: 1 USD ≈ 7.3 CNY
MODEL_PRICING: Dict[str, ModelPricing] = {
    # GPT Series (converted from USD)
    "gpt-5.2": ModelPricing(
        input_price=12.78,      # $1.75 × 7.3
        output_price=102.2      # $14.0 × 7.3
    ),

    # Doubao Series (converted from USD, with context threshold)
    "doubao-seed-1-8-251228": ModelPricing(
        input_price=1.83,
        output_price=14.6,
        input_price_large=3.65,
        output_price_large=29.2,
        context_threshold=131000
    ),

    # Gemini Series (converted from USD)
    "gemini-3-flash-preview": ModelPricing(
        input_price=3.65,       # $0.50 × 7.3
        output_price=21.9       # $3.0 × 7.3
    ),
    "vertex-gemini-3-pro-preview-thinking": ModelPricing(
        input_price=14.6,       # $2.0 × 7.3
        output_price=87.6,      # $12.0 × 7.3
        input_price_large=29.2, # $4.0 × 7.3
        output_price_large=131.4,# $18.0 × 7.3
        context_threshold=200000
    ),

    # DeepSeek Series (converted from USD)
    "deepseek-v3-2-251201": ModelPricing(
        input_price=1.97,       # $0.27 × 7.3
        output_price=2.92       # $0.40 × 7.3
    ),

    # 统一网关接管后补齐的模型（app agent_debug / pdf / translator / 曲线分析在用）。
    # 价格为同档位估值占位，后台 model_pricing 可改。仅兜底全新部署的 seed。
    "qwen3.6-plus": ModelPricing(
        input_price=4.0,
        output_price=12.0,
    ),
    "gemini-3.1-flash-lite-preview": ModelPricing(
        input_price=0.73,       # ~$0.10 × 7.3
        output_price=2.92,      # ~$0.40 × 7.3
    ),
    "gemini-3.1-pro-preview-thinking": ModelPricing(
        input_price=14.6,       # $2.0 × 7.3
        output_price=87.6,      # $12.0 × 7.3
    ),
    "gpt-5-mini": ModelPricing(
        input_price=1.83,       # ~$0.25 × 7.3
        output_price=14.6,      # ~$2.0 × 7.3
    ),
    "gemini-2.5-flash": ModelPricing(
        input_price=2.19,       # $0.30 × 7.3
        output_price=18.25,     # $2.5 × 7.3
    ),

    # Image Generation Models
    "doubao-seedream-4-5-251128": ModelPricing(
        input_price=0,
        output_price=0,
        fixed_price_per_image=2500,  # ¥0.25/image = 2500 (0.0001 CNY units)
    ),
    "vertex-gemini-3-pro-image-preview": ModelPricing(
        input_price=14.6,       # $2 × 7.3
        output_price=87.6       # $12 × 7.3
    ),
}


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> int:
    """
    Calculate request cost.

    Args:
        model: Model name
        prompt_tokens: Input tokens
        completion_tokens: Output tokens

    Returns:
        Cost in 0.0001 CNY units (integer), i.e. 10000 = ¥1.00
    """
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        return 0  # Unknown models have no cost

    # Fixed price per image (e.g., doubao image generation)
    if pricing.fixed_price_per_image is not None:
        return pricing.fixed_price_per_image

    # Check if context exceeds threshold
    if pricing.context_threshold > 0 and prompt_tokens > pricing.context_threshold:
        input_rate = pricing.input_price_large or pricing.input_price
        output_rate = pricing.output_price_large or pricing.output_price
    else:
        input_rate = pricing.input_price
        output_rate = pricing.output_price

    # Calculate cost (CNY per million tokens)
    input_cost = (prompt_tokens / 1_000_000) * input_rate
    output_cost = (completion_tokens / 1_000_000) * output_rate
    total_cost = input_cost + output_cost

    # Convert to 0.0001 CNY units (integer storage)
    return int(total_cost * 10000)
