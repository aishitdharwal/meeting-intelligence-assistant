"""
OpenAI Pricing Calculator

Calculates costs for OpenAI API usage (Whisper and GPT-4o Mini) with caching.
Pricing is fetched from environment variables with hardcoded fallbacks.
"""

import os
from datetime import datetime, timedelta

# Cache pricing for 1 hour to avoid repeated environment variable lookups
_pricing_cache = None
_cache_timestamp = None
_cache_duration = timedelta(hours=1)


def get_pricing():
    """
    Get OpenAI pricing with 1-hour cache.

    Returns:
        dict: Pricing information for Whisper and GPT-4o Mini
            {
                'whisper-1': {
                    'price_per_second': float
                },
                'gpt-4o-mini': {
                    'input_price_per_1k': float,
                    'output_price_per_1k': float
                }
            }
    """
    global _pricing_cache, _cache_timestamp

    # Check cache
    if _pricing_cache and _cache_timestamp:
        if datetime.utcnow() - _cache_timestamp < _cache_duration:
            return _pricing_cache

    # Fetch from environment variables with fallback to hardcoded defaults
    # Default pricing as of January 2026:
    # - Whisper: $0.006 per minute = $0.0001 per second
    # - GPT-4o Mini: $0.15 per 1M input tokens, $0.60 per 1M output tokens
    pricing = {
        'whisper-1': {
            'price_per_second': float(os.environ.get('WHISPER_PRICE_PER_SECOND', '0.0001'))
        },
        'gpt-4o-mini': {
            'input_price_per_1k': float(os.environ.get('GPT4O_MINI_INPUT_PRICE', '0.00015')),
            'output_price_per_1k': float(os.environ.get('GPT4O_MINI_OUTPUT_PRICE', '0.0006'))
        }
    }

    # Update cache
    _pricing_cache = pricing
    _cache_timestamp = datetime.utcnow()

    return pricing


def calculate_whisper_cost(duration_seconds):
    """
    Calculate Whisper API cost based on audio duration.

    Args:
        duration_seconds (float): Audio duration in seconds

    Returns:
        float: Cost in USD
    """
    if duration_seconds <= 0:
        return 0.0

    pricing = get_pricing()
    return duration_seconds * pricing['whisper-1']['price_per_second']


def calculate_gpt4o_mini_cost(prompt_tokens, completion_tokens):
    """
    Calculate GPT-4o Mini cost based on token usage.

    Args:
        prompt_tokens (int): Number of input/prompt tokens
        completion_tokens (int): Number of output/completion tokens

    Returns:
        float: Cost in USD
    """
    if prompt_tokens < 0 or completion_tokens < 0:
        return 0.0

    pricing = get_pricing()
    input_cost = (prompt_tokens / 1000) * pricing['gpt-4o-mini']['input_price_per_1k']
    output_cost = (completion_tokens / 1000) * pricing['gpt-4o-mini']['output_price_per_1k']
    return input_cost + output_cost
