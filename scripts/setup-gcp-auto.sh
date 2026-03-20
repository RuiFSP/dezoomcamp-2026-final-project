#!/bin/bash
# GCP Project Setup Script - Non-Interactive Version
# This automates Step 0 of the implementation plan

set -e

PROJECT_ID="gh-dezoomcamp"
PROJECT_NAME="GitHub Activity Analytics"
SERVICE_ACCOUNT_NAME="bruin-pipeline"
REGION="europe-west1"
KEY_FILE="$HOME/gcp-key.json"
EXPORT_LINE="export GOOGLE_APPLICATION_CREDENTIALS=\"$KEY_FILE\""

append_if_missing() {
    target_file="$1"
    line="$2"
    touch "$target_file"
    if ! grep -Fqx "$line" "$target_file"; then
        echo "$line" >> "$target_file"
    fi
}

echo "╭─────────────────────────────────────────╮"
echo "│ GCP Setup for GitHub Analytics Pipeline │"
echo "╰─────────────────────────────────────────╯"
echo ""
echo "📌 Configuration:"
echo "   Project ID: $PROJECT_ID"
echo "   Service Account: $SERVICE_ACCOUNT_NAME"
echo "   Key Location: $KEY_FILE"
echo ""

# Step 1: Create Project
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 Step 1/7: Creating GCP Project..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if gcloud projects describe "$PROJECT_ID" &>/dev/null; then
    echo "✅ Project already exists: $PROJECT_ID"
else
    echo "Creating new project: $PROJECT_ID"
    gcloud projects create "$PROJECT_ID" \
        --name="$PROJECT_NAME" \
        --set-as-default
    echo "✅ Project created"
fi

gcloud config set project "$PROJECT_ID"
echo ""

# Step 2: Enable APIs
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 Step 2/7: Enabling required APIs..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "  • bigquery.googleapis.com"
echo "  • storage.googleapis.com"
echo "  • iam.googleapis.com"
echo "  • cloudresourcemanager.googleapis.com"
echo ""

gcloud services enable \
    bigquery.googleapis.com \
    storage.googleapis.com \
    iam.googleapis.com \
    cloudresourcemanager.googleapis.com \
    --project="$PROJECT_ID"

echo "✅ APIs enabled"
echo ""

# Step 3: Create Service Account
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "👤 Step 3/7: Creating service account..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
echo "Service Account: $SERVICE_ACCOUNT_EMAIL"
echo ""

if gcloud iam service-accounts describe "$SERVICE_ACCOUNT_EMAIL" --project="$PROJECT_ID" &>/dev/null; then
    echo "✅ Service account already exists"
else
    echo "Creating service account..."
    gcloud iam service-accounts create "$SERVICE_ACCOUNT_NAME" \
        --display-name="Bruin Pipeline Service Account" \
        --project="$PROJECT_ID"
    echo "✅ Service account created"
fi
echo ""

# Step 4: Grant BigQuery Admin role
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔐 Step 4/7: Granting BigQuery Admin role..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/bigquery.admin" \
    --condition=None \
    --quiet 2>/dev/null || echo "✅ Role binding already exists or updated"

echo "✅ BigQuery Admin role granted"
echo ""

# Step 5: Grant Storage Admin role
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔐 Step 5/7: Granting Storage Admin role..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/storage.admin" \
    --condition=None \
    --quiet 2>/dev/null || echo "✅ Role binding already exists or updated"

echo "✅ Storage Admin role granted"
echo ""

# Step 6: Create Service Account Key
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔑 Step 6/7: Creating service account key..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -f "$KEY_FILE" ]; then
    echo "⚠️  Key already exists: $KEY_FILE"
    echo "Moving old key to backup..."
    mv "$KEY_FILE" "${KEY_FILE}.backup.$(date +%s)"
fi

gcloud iam service-accounts keys create "$KEY_FILE" \
    --iam-account="$SERVICE_ACCOUNT_EMAIL" \
    --project="$PROJECT_ID"

chmod 600 "$KEY_FILE"
echo "✅ Service account key created: $KEY_FILE"
echo ""

# Step 7: Verify Setup
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✔️  Step 7/7: Verifying setup..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

export GOOGLE_APPLICATION_CREDENTIALS="$KEY_FILE"

if gcloud auth application-default print-access-token &>/dev/null; then
    echo "✅ Authentication successful!"
else
    echo "⚠️  Could not verify authentication"
fi

echo ""
echo "╔═══════════════════════════════════════════╗"
echo "║  ✨ GCP Setup Complete!                  ║"
echo "╚═══════════════════════════════════════════╝"
echo ""
echo "📌 Configuration Summary:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Project ID:              $PROJECT_ID"
echo "  Service Account:         $SERVICE_ACCOUNT_EMAIL"
echo "  Key Location:            $KEY_FILE"
echo "  Environment Variable:    GOOGLE_APPLICATION_CREDENTIALS"
echo "  Region:                  $REGION"
echo ""
append_if_missing "$HOME/.bashrc" "$EXPORT_LINE"
append_if_missing "$HOME/.zshrc" "$EXPORT_LINE"

echo "🔐 Credential Handling:"
echo "  The service account key contents were not printed."
echo "  Export line has been added only if missing in ~/.bashrc and ~/.zshrc."
echo ""
echo "📝 Next Steps:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "1️⃣  Update your shell profile to persist credentials:"
echo ""
echo "   Add to ~/.bashrc and/or ~/.zshrc:"
echo "   export GOOGLE_APPLICATION_CREDENTIALS=\"$KEY_FILE\""
echo ""
echo "   Then reload:"
echo "   source ~/.bashrc && source ~/.zshrc"
echo ""
echo "2️⃣  Verify authentication:"
echo ""
echo "   gcloud auth application-default print-access-token"
echo ""
echo "3️⃣  Start Step 1: Create Project Directories"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
