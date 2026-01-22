// API endpoint - Replace with your actual endpoint
const API_ENDPOINT = 'https://nzdm4iwlw0.execute-api.ap-south-1.amazonaws.com/prod/submit-s3-video';

const form = document.getElementById('uploadForm');
const s3UriInput = document.getElementById('s3Uri');
const submitBtn = document.getElementById('submitBtn');
const btnText = document.getElementById('btnText');
const btnLoader = document.getElementById('btnLoader');
const resultDiv = document.getElementById('result');
const errorDiv = document.getElementById('error');
const meetingIdSpan = document.getElementById('meetingId');
const errorMessageP = document.getElementById('errorMessage');

form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const s3Uri = s3UriInput.value.trim();

    // Hide previous results
    resultDiv.classList.add('hidden');
    errorDiv.classList.add('hidden');

    // Validate format
    if (!s3Uri.match(/^s3:\/\/[^\/]+\/.+$/)) {
        showError('Invalid S3 URI format. Must be: s3://bucket-name/path/to/file');
        return;
    }

    // Disable form
    submitBtn.disabled = true;
    btnText.textContent = 'Processing...';
    btnLoader.classList.remove('hidden');

    try {
        const response = await fetch(API_ENDPOINT, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ s3_uri: s3Uri })
        });

        const data = await response.json();

        if (response.ok) {
            meetingIdSpan.textContent = data.meeting_id;
            resultDiv.classList.remove('hidden');
            form.reset();
        } else {
            showError(data.error || 'Failed to start processing');
        }
    } catch (error) {
        showError('Network error: ' + error.message);
    } finally {
        // Re-enable form
        submitBtn.disabled = false;
        btnText.textContent = 'Process Video';
        btnLoader.classList.add('hidden');
    }
});

function showError(message) {
    errorMessageP.textContent = message;
    errorDiv.classList.remove('hidden');
}
