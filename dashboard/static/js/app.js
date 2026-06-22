/**
 * Lead-Gen Pipeline — Dashboard Interactivity
 * Handles: post buttons, queue all, Quora copy+open, toast notifications
 */

// ── Toast Notification System ─────────────────────────────────

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    // Auto-dismiss after 3 seconds
    setTimeout(() => {
        toast.classList.add('toast--leaving');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}


// ── Post Single Comment ───────────────────────────────────────

async function postComment(draftId, btnElement) {
    // Set loading state
    btnElement.classList.add('btn--loading');
    btnElement.disabled = true;

    try {
        const response = await fetch(`/api/post/${draftId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });

        const data = await response.json();

        if (response.ok) {
            // Update card visually
            const card = document.getElementById(`lead-${draftId}`);
            if (card) {
                card.classList.add('lead-card--posted');
                // Update status badge
                const badges = card.querySelectorAll('.badge--status-pending, .badge--status-queued');
                badges.forEach(b => {
                    b.className = 'badge badge--status-posted';
                    b.textContent = 'Posted';
                });
                // Replace button with "Posted" indicator
                btnElement.outerHTML = '<span class="btn btn--success" style="cursor:default;">✅ Posted</span>';
            }
            showToast('Comment posted successfully!', 'success');
        } else {
            showToast(`Failed to post: ${data.detail || 'Unknown error'}`, 'error');
            btnElement.classList.remove('btn--loading');
            btnElement.disabled = false;
        }
    } catch (error) {
        showToast(`Network error: ${error.message}`, 'error');
        btnElement.classList.remove('btn--loading');
        btnElement.disabled = false;
    }
}


// ── Queue All Posts ───────────────────────────────────────────

async function queueAll(platform) {
    const btn = document.getElementById('btn-queue-all');
    btn.classList.add('btn--loading');
    btn.disabled = true;

    try {
        const response = await fetch(`/api/post/batch/${platform}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });

        const data = await response.json();

        if (response.ok && data.status === 'queue_started') {
            showToast(`${data.count} comments queued — posting with rate limiting...`, 'success');

            // Update button text to show queue progress
            const btnText = btn.querySelector('.btn-text');
            if (btnText) btnText.textContent = `⏳ Posting ${data.count} comments...`;

            // Poll for queue completion
            let pollCount = 0;
            const maxPolls = data.count * 15; // ~15 seconds per comment (rate limit buffer)

            const pollInterval = setInterval(async () => {
                pollCount++;

                try {
                    const statusResp = await fetch('/api/post/queue-status');
                    const statusData = await statusResp.json();

                    const isRunning = statusData.running && statusData.running[platform];

                    if (!isRunning || pollCount >= maxPolls) {
                        clearInterval(pollInterval);
                        showToast('Queue processing complete! Refreshing...', 'success');
                        setTimeout(() => window.location.reload(), 1500);
                    }
                } catch {
                    // Polling error — keep going
                }
            }, 2000);

        } else if (data.status === 'already_running') {
            showToast('Queue is already being processed. Please wait.', 'info');
            btn.classList.remove('btn--loading');
            btn.disabled = false;
        } else if (data.status === 'empty') {
            showToast('No comments to post.', 'info');
            btn.classList.remove('btn--loading');
            btn.disabled = false;
        } else {
            showToast(`Failed: ${data.detail || data.message || 'Unknown error'}`, 'error');
            btn.classList.remove('btn--loading');
            btn.disabled = false;
        }
    } catch (error) {
        showToast(`Network error: ${error.message}`, 'error');
        btn.classList.remove('btn--loading');
        btn.disabled = false;
    }
}


// ── Quora: Copy & Open ────────────────────────────────────────

async function copyAndOpen(draftId, postUrl, btnElement) {
    // Get the draft text from the data attribute
    const draftText = btnElement.getAttribute('data-draft');

    try {
        // Copy to clipboard
        await navigator.clipboard.writeText(draftText);
        showToast('Answer copied to clipboard! Opening Quora...', 'success');

        // Open the Quora question in a new tab
        window.open(postUrl, '_blank');

        // Mark as posted in the backend
        await fetch(`/api/post/${draftId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });

        // Update card visually
        const card = document.getElementById(`lead-${draftId}`);
        if (card) {
            card.classList.add('lead-card--posted');
            const badges = card.querySelectorAll('.badge--status-pending, .badge--status-queued');
            badges.forEach(b => {
                b.className = 'badge badge--status-posted';
                b.textContent = 'Posted';
            });
            btnElement.outerHTML = '<span class="btn btn--success" style="cursor:default;">✅ Copied</span>';
        }
    } catch (error) {
        // Fallback for clipboard API not available
        showToast('Please copy the answer manually from the card.', 'error');
        window.open(postUrl, '_blank');
    }
}


// ── Reject Draft ─────────────────────────────────────────────

async function rejectDraft(draftId, btnElement) {
    try {
        const response = await fetch(`/api/queue/${draftId}/reject`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
        });

        if (response.ok) {
            const card = document.getElementById(`lead-${draftId}`);
            if (card) {
                card.classList.add('lead-card--rejected');
                const badges = card.querySelectorAll('.badge--status-pending, .badge--status-queued');
                badges.forEach(b => {
                    b.className = 'badge badge--status-rejected';
                    b.textContent = 'Rejected';
                });
                // Replace the entire actions area with a rejected indicator
                const actionsDiv = btnElement.closest('.lead-card-actions');
                if (actionsDiv) {
                    const postLink = actionsDiv.querySelector('a');
                    const linkHtml = postLink ? postLink.outerHTML : '';
                    actionsDiv.innerHTML = linkHtml + '<span class="btn btn--danger" style="cursor: default;">❌ Rejected</span>';
                }
            }
            showToast('Draft rejected.', 'info');
        } else {
            showToast('Failed to reject draft.', 'error');
        }
    } catch (error) {
        showToast(`Network error: ${error.message}`, 'error');
    }
}


// ── Run Ingestion Pipeline ───────────────────────────────────

async function runIngestion(platform, btnElement) {
    // Set loading state
    btnElement.classList.add('btn--loading');
    btnElement.disabled = true;

    // Show progress UI
    const statusEl = document.getElementById('ingestion-status');
    const statusText = document.getElementById('ingestion-status-text');
    const progressFill = document.getElementById('ingestion-progress-fill');

    if (statusEl) {
        statusEl.style.display = 'flex';
        statusText.textContent = `Starting ${platform === 'all' ? 'all platforms' : platform} pipeline...`;
        progressFill.style.width = '10%';
    }

    try {
        const response = await fetch(`/api/ingest/run/${platform}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });

        const data = await response.json();

        if (response.ok && data.status !== 'error') {
            showToast(`Pipeline started for ${platform === 'all' ? 'all platforms' : platform}!`, 'success');

            if (statusText) statusText.textContent = 'Pipeline running — fetching posts...';
            if (progressFill) progressFill.style.width = '30%';

            // Poll for completion
            let pollCount = 0;
            const maxPolls = 120; // 2 minutes max (1 poll per second)

            const pollInterval = setInterval(async () => {
                pollCount++;

                // Update progress bar animation
                const progress = Math.min(30 + (pollCount / maxPolls) * 60, 90);
                if (progressFill) progressFill.style.width = `${progress}%`;

                // Update status text based on progress
                if (pollCount < 10) {
                    if (statusText) statusText.textContent = 'Fetching posts from platforms...';
                } else if (pollCount < 30) {
                    if (statusText) statusText.textContent = 'Running Tier-1 & Tier-2 filters...';
                } else if (pollCount < 60) {
                    if (statusText) statusText.textContent = 'Matching schemes via RAG search...';
                } else {
                    if (statusText) statusText.textContent = 'Generating draft comments...';
                }

                try {
                    const statusResp = await fetch('/api/ingest/status');
                    const statusData = await statusResp.json();

                    // Check if any pipelines are still running
                    const anyRunning = Object.values(statusData.running || {}).some(v => v === true);

                    if (!anyRunning || pollCount >= maxPolls) {
                        clearInterval(pollInterval);

                        if (progressFill) progressFill.style.width = '100%';
                        if (statusText) statusText.textContent = 'Pipeline complete! Refreshing...';

                        showToast('Pipeline complete! Refreshing dashboard...', 'success');

                        // Reload after a brief pause to show completion
                        setTimeout(() => window.location.reload(), 1500);
                    }
                } catch {
                    // Polling error — keep going
                }
            }, 1000);

        } else {
            showToast(`${data.message || 'Failed to start pipeline'}`, 'error');
            btnElement.classList.remove('btn--loading');
            btnElement.disabled = false;
            if (statusEl) statusEl.style.display = 'none';
        }
    } catch (error) {
        showToast(`Network error: ${error.message}`, 'error');
        btnElement.classList.remove('btn--loading');
        btnElement.disabled = false;
        if (statusEl) statusEl.style.display = 'none';
    }
}


// ── Page load: Add subtle entrance animations ─────────────────

document.addEventListener('DOMContentLoaded', () => {
    // Stagger card animations
    const cards = document.querySelectorAll('.lead-card');
    cards.forEach((card, index) => {
        card.style.animationDelay = `${index * 0.05}s`;
    });
});
