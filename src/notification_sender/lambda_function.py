"""
Notification Sender Lambda
Sends notifications via Slack (and optionally SES)
"""

import json
import os
import boto3
import requests
from datetime import datetime

secretsmanager = boto3.client('secretsmanager')
ses = boto3.client('ses')

SLACK_WEBHOOK_SECRET_NAME = os.environ['SLACK_WEBHOOK_SECRET_NAME']
EMAIL_RECIPIENTS_SECRET_NAME = os.environ['EMAIL_RECIPIENTS_SECRET_NAME']


def get_slack_webhook_url():
    """Retrieve Slack webhook URL from Secrets Manager"""
    try:
        response = secretsmanager.get_secret_value(SecretId=SLACK_WEBHOOK_SECRET_NAME)
        return response['SecretString']
    except Exception as e:
        print(f"Error retrieving Slack webhook URL: {e}")
        return None


def get_email_recipients():
    """Retrieve email recipients from Secrets Manager"""
    try:
        response = secretsmanager.get_secret_value(SecretId=EMAIL_RECIPIENTS_SECRET_NAME)
        recipients = json.loads(response['SecretString'])
        # Filter out placeholder emails
        return [r for r in recipients if 'placeholder' not in r.lower() and 'example.com' not in r.lower()]
    except Exception as e:
        print(f"Error retrieving email recipients: {e}")
        return []


def format_action_items(action_items):
    """Format action items as a list"""
    if not action_items:
        return "No action items identified"

    formatted = []
    for i, item in enumerate(action_items, 1):
        action = item.get('action', 'Unknown action')
        owner = item.get('owner', 'Unassigned')
        due = item.get('due_date', 'Not specified')
        mentioned = item.get('mentioned_at', '')

        formatted.append(f"{i}. {action}")
        formatted.append(f"   Owner: {owner} | Due: {due}")
        if mentioned:
            formatted.append(f"   Mentioned: {mentioned}")
        formatted.append("")  # Blank line

    return '\n'.join(formatted)


def send_slack_notification(meeting_name, duration, summary, action_items):
    """Send notification to Slack"""
    webhook_url = get_slack_webhook_url()

    if not webhook_url:
        print("Slack webhook URL not configured - skipping Slack notification")
        return False

    try:
        # Format action items for Slack
        action_items_text = format_action_items(action_items)

        # Create Slack message
        message = {
            "text": f"📊 Meeting Intelligence Report: {meeting_name}",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "📊 Meeting Intelligence Report"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Meeting:*\n{meeting_name}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Duration:*\n{duration}"
                        }
                    ]
                },
                {
                    "type": "divider"
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Summary:*\n{summary[:2000]}"  # Slack has limits
                    }
                },
                {
                    "type": "divider"
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Action Items:*\n{action_items_text[:2000]}"
                    }
                }
            ]
        }

        # Send to Slack
        response = requests.post(
            webhook_url,
            json=message,
            timeout=10
        )

        if response.status_code == 200:
            print("Slack notification sent successfully")
            return True
        else:
            print(f"Slack notification failed: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        print(f"Error sending Slack notification: {e}")
        return False


def send_email_notification(meeting_name, duration, summary, action_items):
    """Send email notification via SES"""
    recipients = get_email_recipients()

    if not recipients:
        print("No email recipients configured - skipping email notification")
        return False

    try:
        # Format email body
        action_items_text = format_action_items(action_items)

        subject = f"Meeting Intelligence Report - {meeting_name}"

        body = f"""Meeting Intelligence Report

Meeting: {meeting_name}
Duration: {duration}
Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}

═══════════════════════════════════════════════

SUMMARY:

{summary}

═══════════════════════════════════════════════

ACTION ITEMS:

{action_items_text}

═══════════════════════════════════════════════

This is an automated report generated by Meeting Intelligence Assistant.
Full transcript and details are available in the system database.
"""

        # Send email
        response = ses.send_email(
            Source='noreply@yourdomain.com',  # Update this with verified SES email
            Destination={
                'ToAddresses': recipients
            },
            Message={
                'Subject': {
                    'Data': subject,
                    'Charset': 'UTF-8'
                },
                'Body': {
                    'Text': {
                        'Data': body,
                        'Charset': 'UTF-8'
                    }
                }
            }
        )

        print(f"Email sent successfully to {len(recipients)} recipients")
        print(f"SES Message ID: {response['MessageId']}")
        return True

    except Exception as e:
        print(f"Error sending email: {e}")
        # Check if it's a not-verified error
        if 'not verified' in str(e).lower():
            print("NOTE: Email address not verified in SES. Please verify sender email in AWS SES console.")
        return False


def lambda_handler(event, context):
    """Main handler for sending notifications"""
    print(f"Received event: {json.dumps(event)}")

    try:
        # Extract data from event
        final_result = event.get('finalResult', event)

        meeting_name = final_result.get('meeting_name', 'Unknown Meeting')
        duration = final_result.get('duration', 'Unknown')
        summary = final_result.get('final_summary', 'No summary available')
        action_items = final_result.get('action_items', [])

        print(f"Sending notifications for meeting: {meeting_name}")
        print(f"Action items: {len(action_items)}")

        # Send Slack notification
        slack_success = send_slack_notification(meeting_name, duration, summary, action_items)

        # Send email notification (optional)
        email_success = send_email_notification(meeting_name, duration, summary, action_items)

        # Prepare result
        result = {
            'slack_sent': slack_success,
            'email_sent': email_success,
            'timestamp': datetime.utcnow().isoformat()
        }

        # Don't fail if notifications fail - just log
        if not slack_success and not email_success:
            print("WARNING: Both notification methods failed")
        elif not slack_success:
            print("WARNING: Slack notification failed")
        elif not email_success:
            print("WARNING: Email notification failed (this is expected if SES not configured)")

        print(f"Notification result: {json.dumps(result)}")
        return result

    except Exception as e:
        print(f"Error in notification sender: {e}")
        import traceback
        traceback.print_exc()

        # Don't raise - notifications are not critical
        # Return error result but don't fail workflow
        return {
            'slack_sent': False,
            'email_sent': False,
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }
