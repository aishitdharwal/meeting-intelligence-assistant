# Fix for pyparsing Error

## Problem

Getting this error when running the webhook registration script:
```
AttributeError: module 'pyparsing' has no attribute 'DelimitedList'. Did you mean: 'delimitedList'?
```

## Solution

The issue is caused by incompatibility between `google-api-python-client` and `pyparsing>=3.0.0`.

### Quick Fix

Uninstall and reinstall with the correct version constraints:

```bash
# Uninstall the problematic packages
pip uninstall -y pyparsing google-api-python-client google-auth google-auth-oauthlib google-auth-httplib2

# Install with correct versions
pip install -r config/requirements.txt
```

### Alternative: Use a Virtual Environment (Recommended)

```bash
# Create a virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate  # On macOS/Linux
# or
venv\Scripts\activate     # On Windows

# Install dependencies
pip install -r config/requirements.txt

# Run the webhook registration script
python config/register_webhook.py
```

### Verify the Fix

```bash
python -c "import pyparsing; print(f'pyparsing version: {pyparsing.__version__}')"
```

Should show: `pyparsing version: 2.x.x` (not 3.x.x)

## Why This Happens

- `pyparsing 3.x` changed `DelimitedList` to `delimitedList` (lowercase)
- Older versions of `google-api-python-client` use the old capitalized name
- Pinning `pyparsing<3.0.0` ensures compatibility

## Already Fixed In

✅ Lambda function `video_downloader/requirements.txt` - includes `pyparsing<3.0.0`
✅ Config folder `config/requirements.txt` - for local webhook registration

The deployed Lambda functions will work fine because they use the fixed requirements.txt!
