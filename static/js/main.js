/**
 * CodeLens AI - Main JavaScript Controller (Phase 4)
 * Handles:
 * 1. Single & Multiple GitHub repository URL intake & real-time validation (Phase 2)
 * 2. Dynamic queue management (1–10 URLs) and removal (Phase 2)
 * 3. Keyword-based GitHub repository discovery via GitHub API (Phase 3)
 * 4. Repository Suitability Ranking & Evaluation (Phase 4)
 * 5. Recommended Repository identification and manual selection override (Phase 4)
 */

// Application State
const MAX_REPOSITORIES = 10;
let repositories = [];
let currentSearchResults = [];
let lastSearchKeyword = '';
let activeTargetRepository = null;

/**
 * Synchronize repository query parameter across all top navigation links.
 * @param {string} repoFullName
 */
function syncNavigationRepoParams(repoFullName) {
    if (!repoFullName) return;
    const encoded = encodeURIComponent(repoFullName);
    document.querySelectorAll('.navbar .nav-links a').forEach(link => {
        const href = link.getAttribute('href') || '';
        if (href.includes('/architecture') || href.includes('/chat') || href.includes('/report') || href.includes('/analysis')) {
            const cleanPath = href.split('?')[0];
            link.setAttribute('href', `${cleanPath}?repo=${encoded}`);
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    console.log('[CodeLens AI] Product controller initialized.');

    // Pre-sync navigation links if repository is in URL or localStorage
    const urlParams = new URLSearchParams(window.location.search);
    let initialRepo = urlParams.get('repo');
    if (!initialRepo) {
        try {
            initialRepo = localStorage.getItem('codelens_last_repo');
        } catch (e) {}
    }
    if (initialRepo) {
        syncNavigationRepoParams(initialRepo);
    }

    initRepoIntake();
    initSampleChips();
    initKeywordSearch();
    initRankingActions();
    initAnalysisPage();
    initArchitecturePage();
    initSemanticGraphPage();
    initReportPage();
    initChatPage();
});

/**
 * Initialize repository intake form, queue interactions, and analyze action.
 */
function initRepoIntake() {
    const form = document.getElementById('add-repo-form');
    const input = document.getElementById('repo-url');
    const btnAnalyze = document.getElementById('btn-analyze');
    const btnClearAll = document.getElementById('btn-clear-all');
    const btnFocusAdd = document.getElementById('btn-focus-add');

    // Handle form submit (Add Repository by URL)
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const rawUrl = (input ? input.value : '').trim();
            await handleAddRepository(rawUrl);
        });
    }

    // Handle Focus Add button in queue footer
    if (btnFocusAdd && input) {
        btnFocusAdd.addEventListener('click', () => {
            input.focus();
            input.scrollIntoView({ behavior: 'smooth', block: 'center' });
        });
    }

    // Handle Clear All
    if (btnClearAll) {
        btnClearAll.addEventListener('click', () => {
            if (repositories.length === 0) return;
            repositories = [];
            activeTargetRepository = null;
            renderRepositoryList();
            updateSearchResultButtons();
            hideRankingResults();
            showFeedback('url-feedback', 'All repositories removed from queue.', 'warning');
            showToast('Queue Cleared', 'All repositories have been removed.');
        });
    }

    // Handle Analyze (Evaluate & Rank Repositories)
    if (btnAnalyze) {
        btnAnalyze.addEventListener('click', async () => {
            await handleAnalyzeClick();
        });
    }

    // Clear feedback on input typing
    if (input) {
        input.addEventListener('input', () => {
            input.classList.remove('input-error');
            hideFeedback('url-feedback');
        });
    }
}

/**
 * Handle adding a repository via backend validation endpoint.
 * @param {string} rawUrl
 */
async function handleAddRepository(rawUrl) {
    const input = document.getElementById('repo-url');

    // 1. Client-side check for empty input
    if (!rawUrl) {
        showFeedback('url-feedback', 'Please enter a GitHub repository URL.', 'error');
        if (input) {
            input.classList.add('input-error');
            input.focus();
        }
        return;
    }

    // 2. Client-side limit check (1-10 URLs)
    if (repositories.length >= MAX_REPOSITORIES) {
        const limitMsg = `Maximum limit reached (${MAX_REPOSITORIES} repositories). Remove an existing repository before adding another.`;
        showFeedback('url-feedback', limitMsg, 'error');
        showToast('Limit Reached', limitMsg, 'error');
        return;
    }

    // 3. Send to backend validation endpoint: POST /api/repositories/validate
    try {
        setAddingState(true);
        hideFeedback('url-feedback');

        const response = await fetch('/api/repositories/validate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: rawUrl })
        });

        const data = await response.json();

        if (!response.ok || !data.valid) {
            const errorMsg = data.error || 'Invalid repository URL.';
            showFeedback('url-feedback', errorMsg, 'error');
            if (input) {
                input.classList.add('input-error');
                input.focus();
            }
            showToast('Validation Error', errorMsg, 'error');
            return;
        }

        const repoData = data.repository;

        // 4. Duplicate Check
        const isDuplicate = isRepoInQueue(repoData.owner, repoData.name);
        if (isDuplicate) {
            const dupMsg = `Repository '${repoData.owner}/${repoData.name}' is already in your list.`;
            showFeedback('url-feedback', dupMsg, 'error');
            if (input) {
                input.classList.add('input-error');
                input.focus();
            }
            showToast('Duplicate Repository', dupMsg, 'error');
            return;
        }

        // 5. Add to collection
        repositories.push({
            url: repoData.url,
            owner: repoData.owner,
            name: repoData.name
        });

        // Clear input and update UI
        if (input) {
            input.value = '';
            input.classList.remove('input-error');
            input.focus();
        }

        showFeedback('url-feedback', `Added '${repoData.owner}/${repoData.name}' successfully.`, 'success');
        showToast('Repository Added', `${repoData.owner}/${repoData.name} added to queue.`, 'success');
        hideRankingResults();
        renderRepositoryList();
        updateSearchResultButtons();

    } catch (err) {
        console.error('[CodeLens AI] Validation request failed:', err);
        showFeedback('url-feedback', 'Failed to reach validation service. Please check your connection.', 'error');
    } finally {
        setAddingState(false);
    }
}

/**
 * Check if a repository is already in the queue (case-insensitive).
 */
function isRepoInQueue(owner, name) {
    if (!owner || !name) return false;
    return repositories.some(item =>
        item.owner.toLowerCase() === owner.toLowerCase() &&
        item.name.toLowerCase() === name.toLowerCase()
    );
}

/**
 * Handle clicking Analyze.
 * Evaluates, calculates analysis suitability percentages, and ranks all queued repositories.
 */
async function handleAnalyzeClick() {
    const btnAnalyze = document.getElementById('btn-analyze');
    const keywordInput = document.getElementById('keyword-input');
    const currentKeyword = (keywordInput ? keywordInput.value.trim() : '') || lastSearchKeyword;

    if (repositories.length === 0) {
        showFeedback('url-feedback', 'Please add at least 1 repository before analyzing.', 'error');
        showToast('Empty Queue', 'Add at least 1 repository URL first.', 'error');
        return;
    }

    try {
        if (btnAnalyze) {
            btnAnalyze.disabled = true;
            btnAnalyze.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="spin">
                    <circle cx="12" cy="12" r="10" stroke-opacity="0.25"></circle>
                    <path d="M12 2a10 10 0 0 1 10 10"></path>
                </svg>
                <span>Evaluating &amp; Ranking...</span>
            `;
        }

        // Call backend evaluation & ranking endpoint: POST /api/repositories/analyze
        const response = await fetch('/api/repositories/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                repositories: repositories,
                keyword: currentKeyword || undefined
            })
        });

        const result = await response.json();

        if (!response.ok || !result.success) {
            const errorMsg = result.error || result.message || 'Failed to evaluate repositories.';
            showFeedback('url-feedback', errorMsg, 'error');
            showToast('Evaluation Error', errorMsg, 'error');
            return;
        }

        // Render Ranking Output
        renderRankingResults(result);
        const top = result.recommended_repository;
        showToast(
            'Evaluation Complete',
            `Rank 1: ${top.full_name} recommended (${top.suitability_percentage}% suitability).`,
            'success'
        );

    } catch (err) {
        console.error('[CodeLens AI] Analyze request failed:', err);
        showFeedback('url-feedback', 'An unexpected error occurred while ranking repositories.', 'error');
    } finally {
        if (btnAnalyze) {
            btnAnalyze.disabled = repositories.length === 0;
            btnAnalyze.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <polygon points="5 3 19 12 5 21 5 3"></polygon>
                </svg>
                <span>Analyze</span>
            `;
        }
    }
}

/**
 * Render Phase 4 Ranking Output and Recommended Repository.
 * @param {object} result
 */
function renderRankingResults(result) {
    const card = document.getElementById('ranking-results-card');
    const countBadge = document.getElementById('ranking-count-badge');
    const rec = result.recommended_repository;
    const ranking = result.ranking || [];

    if (!card || !rec) return;

    if (countBadge) {
        countBadge.textContent = `${result.count} Evaluated`;
    }

    // 1. Populate Recommended Repository Card
    const recName = document.getElementById('recommended-name');
    const recUrl = document.getElementById('recommended-url');
    const recScore = document.getElementById('recommended-suitability');
    const recReason = document.getElementById('recommended-reason');

    if (recName) recName.textContent = rec.full_name;
    if (recUrl) {
        recUrl.textContent = rec.url;
        recUrl.href = rec.url;
    }
    if (recScore) recScore.textContent = `${rec.suitability_percentage}% Suitability`;
    if (recReason) recReason.textContent = rec.reason;

    // Factors Progress Bars
    const f = rec.factors || {};
    setBar('bar-kw', 'val-kw', f.keyword_relevance || 0);
    setBar('bar-arch', 'val-arch', f.code_architecture || 0);
    setBar('bar-doc', 'val-doc', f.documentation || 0);
    setBar('bar-act', 'val-act', f.completeness_activity || 0);

    // 2. Populate All Ranked Alternatives
    const list = document.getElementById('ranked-items-list');
    if (list) {
        list.innerHTML = '';

        ranking.forEach((item) => {
            const isRec = item.rank === 1;
            const scoreClass = item.suitability_percentage >= 80 ? 'score-high' :
                               (item.suitability_percentage >= 60 ? 'score-med' : 'score-low');

            const itemCard = document.createElement('div');
            itemCard.className = `ranked-repo-card ${isRec ? 'active-target' : ''}`;
            itemCard.setAttribute('data-target-repo', item.full_name);

            itemCard.innerHTML = `
                <div class="ranked-top-row">
                    <div class="ranked-identity">
                        <span class="rank-badge ${item.rank === 1 ? 'rank-1' : ''}">Rank ${item.rank}</span>
                        <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer" class="ranked-repo-title">
                            ${escapeHtml(item.full_name)}
                        </a>
                    </div>
                    <span class="ranked-score-badge ${scoreClass}">${item.suitability_percentage}% Suitability</span>
                </div>

                <p class="ranked-reason">${escapeHtml(item.reason)}</p>

                <div class="ranked-meta-row">
                    <div class="ranked-tags">
                        <span class="meta-chip">Lang: ${escapeHtml(item.language)}</span>
                        <span class="meta-chip">★ ${Number(item.stars || 0).toLocaleString()}</span>
                        <span class="meta-chip">Size: ${Number(item.size_kb || 0).toLocaleString()} KB</span>
                        ${item.license ? `<span class="meta-chip">${escapeHtml(item.license)}</span>` : ''}
                    </div>
                    <button type="button" class="btn-select-target ${isRec ? 'is-selected' : ''}" data-repo-name="${escapeHtml(item.full_name)}" data-repo-score="${item.suitability_percentage}">
                        ${isRec ? 'Selected ✓' : 'Select'}
                    </button>
                </div>
            `;

            // Attach Select event on card button
            const selectBtn = itemCard.querySelector('.btn-select-target');
            if (selectBtn) {
                selectBtn.addEventListener('click', () => {
                    setActiveTarget(item);
                });
            }

            list.appendChild(itemCard);
        });
    }

    // Set initial active target to Recommended Repository
    setActiveTarget(rec);

    card.classList.remove('hidden');
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/**
 * Set helper for factor progress bar.
 */
function setBar(barId, valId, score) {
    const bar = document.getElementById(barId);
    const val = document.getElementById(valId);
    const clamped = Math.max(0, Math.min(100, Math.round(score)));
    if (bar) bar.style.width = `${clamped}%`;
    if (val) val.textContent = `${clamped}%`;
}

/**
 * Initialize button actions for Recommended Repository.
 */
function initRankingActions() {
    const btnAnalyzeRec = document.getElementById('btn-analyze-recommended');
    if (btnAnalyzeRec) {
        btnAnalyzeRec.addEventListener('click', () => {
            if (activeTargetRepository) {
                window.location.href = `/analysis?repo=${encodeURIComponent(activeTargetRepository.full_name)}`;
            }
        });
    }
}

/**
 * Set active target repository for subsequent comprehension stages.
 * @param {object} repo
 */
function setActiveTarget(repo) {
    activeTargetRepository = repo;

    try {
        localStorage.setItem('codelens_last_repo', repo.full_name);
    } catch (e) {}
    syncNavigationRepoParams(repo.full_name);

    const targetName = document.getElementById('active-target-name');
    const targetScore = document.getElementById('active-target-score');
    const btnProceed = document.getElementById('btn-proceed-phase5');

    if (targetName) targetName.textContent = repo.full_name;
    if (targetScore) targetScore.textContent = `${repo.suitability_percentage}% Suitability`;
    if (btnProceed) {
        btnProceed.href = `/analysis?repo=${encodeURIComponent(repo.full_name)}`;
    }

    // Update buttons in ranked list
    const cards = document.querySelectorAll('.ranked-repo-card');
    cards.forEach(card => {
        const repoAttr = card.getAttribute('data-target-repo');
        const btn = card.querySelector('.btn-select-target');
        if (repoAttr === repo.full_name) {
            card.classList.add('active-target');
            if (btn) {
                btn.classList.add('is-selected');
                btn.textContent = 'Selected ✓';
            }
        } else {
            card.classList.remove('active-target');
            if (btn) {
                btn.classList.remove('is-selected');
                btn.textContent = 'Select';
            }
        }
    });
}

function hideRankingResults() {
    const card = document.getElementById('ranking-results-card');
    if (card) card.classList.add('hidden');
}

/**
 * Render the dynamic list of repositories to analyze.
 */
function renderRepositoryList() {
    const listElement = document.getElementById('repo-list');
    const emptyState = document.getElementById('queue-empty-state');
    const counterBadge = document.getElementById('queue-counter');
    const btnClearAll = document.getElementById('btn-clear-all');
    const btnAnalyze = document.getElementById('btn-analyze');

    if (!listElement) return;

    // Update Counter
    if (counterBadge) {
        counterBadge.textContent = `${repositories.length} / ${MAX_REPOSITORIES} added`;
        if (repositories.length >= MAX_REPOSITORIES) {
            counterBadge.className = 'badge badge-success';
        } else {
            counterBadge.className = 'badge badge-primary';
        }
    }

    // Toggle Empty State vs List
    if (repositories.length === 0) {
        if (emptyState) emptyState.classList.remove('hidden');
        if (btnClearAll) btnClearAll.classList.add('hidden');
        if (btnAnalyze) btnAnalyze.disabled = true;
        listElement.innerHTML = '';
        return;
    }

    if (emptyState) emptyState.classList.add('hidden');
    if (btnClearAll) btnClearAll.classList.remove('hidden');
    if (btnAnalyze) btnAnalyze.disabled = false;

    // Build List Items
    listElement.innerHTML = '';

    repositories.forEach((repo, index) => {
        const itemNumber = index + 1;
        const li = document.createElement('li');
        li.className = 'repo-item';
        li.innerHTML = `
            <div class="repo-info">
                <div class="repo-number">${itemNumber}</div>
                <div class="repo-details">
                    <div class="repo-full-name">
                        <span class="repo-owner">${escapeHtml(repo.owner)}</span>/${escapeHtml(repo.name)}
                    </div>
                    <a href="${escapeHtml(repo.url)}" target="_blank" rel="noopener noreferrer" class="repo-url-link">
                        ${escapeHtml(repo.url)}
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                            <polyline points="15 3 21 3 21 9"></polyline>
                            <line x1="10" y1="14" x2="21" y2="3"></line>
                        </svg>
                    </a>
                </div>
            </div>
            <div class="repo-actions">
                <button type="button" class="btn-remove" data-index="${index}" title="Remove repository">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                    <span>Remove</span>
                </button>
            </div>
        `;

        // Attach Remove Event
        const removeBtn = li.querySelector('.btn-remove');
        if (removeBtn) {
            removeBtn.addEventListener('click', () => {
                removeRepository(index);
            });
        }

        listElement.appendChild(li);
    });
}

/**
 * Remove a repository by index.
 * @param {number} index
 */
function removeRepository(index) {
    if (index >= 0 && index < repositories.length) {
        const removed = repositories.splice(index, 1)[0];
        renderRepositoryList();
        updateSearchResultButtons();
        hideRankingResults();
        showFeedback('url-feedback', `Removed '${removed.owner}/${removed.name}'.`, 'warning');
        showToast('Repository Removed', `${removed.owner}/${removed.name} removed from queue.`);
    }
}

/**
 * Toggle Add button loading state.
 * @param {boolean} isAdding
 */
function setAddingState(isAdding) {
    const btn = document.getElementById('btn-add-repo');
    if (!btn) return;

    btn.disabled = isAdding;
    if (isAdding) {
        btn.innerHTML = `
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="spin">
                <circle cx="12" cy="12" r="10" stroke-opacity="0.25"></circle>
                <path d="M12 2a10 10 0 0 1 10 10"></path>
            </svg>
            <span>Validating...</span>
        `;
    } else {
        btn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="12" y1="5" x2="12" y2="19"></line>
                <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
            <span>Add Repository</span>
        `;
    }
}

/* ==============================================================================
   Phase 3: Keyword Repository Search & Selection
   ============================================================================== */

/**
 * Initialize keyword search form and controls.
 */
function initKeywordSearch() {
    const form = document.getElementById('keyword-search-form');
    const input = document.getElementById('keyword-input');

    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const keyword = (input ? input.value : '').trim();
            await executeKeywordSearch(keyword);
        });
    }

    if (input) {
        input.addEventListener('input', () => {
            input.classList.remove('input-error');
            hideFeedback('keyword-feedback');
        });
    }
}

/**
 * Execute keyword search against backend GitHub API service.
 * @param {string} keyword
 */
async function executeKeywordSearch(keyword) {
    const input = document.getElementById('keyword-input');
    const btnSearch = document.getElementById('btn-search-keyword');
    const resultsWrapper = document.getElementById('search-results-wrapper');

    // 1. Validate empty keyword
    if (!keyword) {
        showFeedback('keyword-feedback', 'Please enter a search keyword (e.g. Python, Machine Learning).', 'error');
        if (input) {
            input.classList.add('input-error');
            input.focus();
        }
        if (resultsWrapper) resultsWrapper.classList.add('hidden');
        return;
    }

    lastSearchKeyword = keyword;

    try {
        setSearchingState(true);
        hideFeedback('keyword-feedback');

        const response = await fetch('/api/repositories/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ q: keyword, per_page: 10 })
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            const errorMsg = data.error || data.message || 'GitHub search failed.';
            showFeedback('keyword-feedback', errorMsg, 'error');
            showToast('Search Failed', errorMsg, 'error');
            if (resultsWrapper) resultsWrapper.classList.add('hidden');
            return;
        }

        // Handle zero results
        if (!data.repositories || data.repositories.length === 0) {
            showFeedback(
                'keyword-feedback',
                `No public repositories found matching keyword '${keyword}'. Try a broader topic.`,
                'warning'
            );
            if (resultsWrapper) resultsWrapper.classList.add('hidden');
            currentSearchResults = [];
            return;
        }

        currentSearchResults = data.repositories;
        renderSearchResults(keyword, data);

    } catch (err) {
        console.error('[CodeLens AI] Search request failed:', err);
        showFeedback('keyword-feedback', 'Failed to reach search service. Please check your network connection.', 'error');
        if (resultsWrapper) resultsWrapper.classList.add('hidden');
    } finally {
        setSearchingState(false);
    }
}

/**
 * Render GitHub candidate repository cards.
 * @param {string} keyword
 * @param {object} data
 */
function renderSearchResults(keyword, data) {
    const resultsWrapper = document.getElementById('search-results-wrapper');
    const heading = document.getElementById('results-heading');
    const countBadge = document.getElementById('results-count-badge');
    const list = document.getElementById('search-results-list');

    if (!resultsWrapper || !list) return;

    if (heading) heading.textContent = `Candidates for "${keyword}"`;
    if (countBadge) {
        const totalFormatted = (data.total_count || data.count).toLocaleString();
        countBadge.textContent = `${data.count} shown (${totalFormatted} total on GitHub)`;
    }

    list.innerHTML = '';

    data.repositories.forEach((repo) => {
        const inQueue = isRepoInQueue(repo.owner, repo.name);
        const card = document.createElement('div');
        card.className = 'search-result-card';

        // Topics Pills HTML
        let topicsHtml = '';
        if (Array.isArray(repo.topics) && repo.topics.length > 0) {
            const displayTopics = repo.topics.slice(0, 5);
            topicsHtml = `
                <div class="result-topics">
                    ${displayTopics.map(t => `<span class="topic-tag">${escapeHtml(t)}</span>`).join('')}
                    ${repo.topics.length > 5 ? `<span class="topic-tag">+${repo.topics.length - 5}</span>` : ''}
                </div>
            `;
        }

        const forkBadgeHtml = repo.is_fork
            ? `<span class="badge badge-fork">Fork</span>`
            : `<span class="badge badge-source">Source</span>`;

        const starsFormatted = Number(repo.stars || 0).toLocaleString();

        card.innerHTML = `
            <div class="result-card-top">
                <div class="result-title-group">
                    <a href="${escapeHtml(repo.url)}" target="_blank" rel="noopener noreferrer" class="result-repo-link">
                        <span class="result-owner">${escapeHtml(repo.owner)}</span>/${escapeHtml(repo.name)}
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                            <polyline points="15 3 21 3 21 9"></polyline>
                            <line x1="10" y1="14" x2="21" y2="3"></line>
                        </svg>
                    </a>
                </div>
                <div class="result-badges">
                    ${forkBadgeHtml}
                </div>
            </div>

            <div class="result-meta-row">
                <div class="meta-item meta-stars">
                    <svg width="13" height="13" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon>
                    </svg>
                    <span>${starsFormatted}</span>
                </div>
                <div class="meta-item meta-language">
                    <span class="lang-dot"></span>
                    <span>${escapeHtml(repo.language || 'Not specified')}</span>
                </div>
            </div>

            <p class="result-description">${escapeHtml(repo.description || 'No description provided.')}</p>

            ${topicsHtml}

            <div class="result-card-bottom">
                <button
                    type="button"
                    class="btn-select-repo ${inQueue ? 'selected' : ''}"
                    data-url="${escapeHtml(repo.url)}"
                    data-owner="${escapeHtml(repo.owner)}"
                    data-name="${escapeHtml(repo.name)}"
                    ${inQueue ? 'disabled' : ''}
                >
                    ${inQueue ? `
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                            <polyline points="20 6 9 17 4 12"></polyline>
                        </svg>
                        <span>Selected ✓</span>
                    ` : `
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                            <line x1="12" y1="5" x2="12" y2="19"></line>
                            <line x1="5" y1="12" x2="19" y2="12"></line>
                        </svg>
                        <span>Select Repository</span>
                    `}
                </button>
            </div>
        `;

        // Handle Select Repository Click
        const selectBtn = card.querySelector('.btn-select-repo');
        if (selectBtn) {
            selectBtn.addEventListener('click', () => {
                selectRepositoryFromSearch(repo, selectBtn);
            });
        }

        list.appendChild(card);
    });

    resultsWrapper.classList.remove('hidden');
    resultsWrapper.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/**
 * Add candidate repository to Phase 2 queue.
 * @param {object} repo
 * @param {HTMLElement} btnElement
 */
function selectRepositoryFromSearch(repo, btnElement) {
    // 1. Boundary check (max 10)
    if (repositories.length >= MAX_REPOSITORIES) {
        const limitMsg = `Maximum limit reached (${MAX_REPOSITORIES} repositories). Remove one repository before selecting another.`;
        showFeedback('keyword-feedback', limitMsg, 'error');
        showToast('Limit Reached', limitMsg, 'error');
        return;
    }

    // 2. Duplicate check
    if (isRepoInQueue(repo.owner, repo.name)) {
        const dupMsg = `Repository '${repo.owner}/${repo.name}' is already in your analysis queue.`;
        showFeedback('keyword-feedback', dupMsg, 'error');
        showToast('Already Selected', dupMsg, 'error');
        return;
    }

    // 3. Add to queue
    repositories.push({
        url: repo.url,
        owner: repo.owner,
        name: repo.name
    });

    // 4. Update Button Appearance
    btnElement.classList.add('selected');
    btnElement.disabled = true;
    btnElement.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
        <span>Selected ✓</span>
    `;

    // 5. Update Phase 2 queue display
    hideRankingResults();
    renderRepositoryList();
    showToast('Repository Added', `Added ${repo.owner}/${repo.name} to analysis queue.`, 'success');
}

/**
 * Synchronize search result card buttons with the queue state.
 */
function updateSearchResultButtons() {
    const buttons = document.querySelectorAll('.btn-select-repo');
    buttons.forEach(btn => {
        const owner = btn.getAttribute('data-owner');
        const name = btn.getAttribute('data-name');
        if (!owner || !name) return;

        const inQueue = isRepoInQueue(owner, name);
        if (inQueue) {
            btn.classList.add('selected');
            btn.disabled = true;
            btn.innerHTML = `
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                <span>Selected ✓</span>
            `;
        } else {
            btn.classList.remove('selected');
            btn.disabled = false;
            btn.innerHTML = `
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <line x1="12" y1="5" x2="12" y2="19"></line>
                    <line x1="5" y1="12" x2="19" y2="12"></line>
                </svg>
                <span>Select Repository</span>
            `;
        }
    });
}

/**
 * Toggle Searching button state.
 * @param {boolean} isSearching
 */
function setSearchingState(isSearching) {
    const btn = document.getElementById('btn-search-keyword');
    if (!btn) return;

    btn.disabled = isSearching;
    if (isSearching) {
        btn.innerHTML = `
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="spin">
                <circle cx="12" cy="12" r="10" stroke-opacity="0.25"></circle>
                <path d="M12 2a10 10 0 0 1 10 10"></path>
            </svg>
            <span>Searching...</span>
        `;
    } else {
        btn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="11" cy="11" r="8"></circle>
                <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
            <span>Search</span>
        `;
    }
}

/**
 * Show inline feedback banner.
 * @param {string} bannerId
 * @param {string} message
 * @param {'error'|'success'|'warning'} type
 */
function showFeedback(bannerId, message, type = 'error') {
    const banner = document.getElementById(bannerId);
    if (!banner) return;

    banner.className = `feedback-banner ${type}`;
    banner.textContent = message;
    banner.classList.remove('hidden');
}

function hideFeedback(bannerId) {
    const banner = document.getElementById(bannerId);
    if (banner) {
        banner.className = 'feedback-banner hidden';
        banner.textContent = '';
    }
}

/**
 * Initialize sample quick-fill chips for both direct URLs and keywords.
 */
function initSampleChips() {
    // Direct URL sample chips
    const urlChips = document.querySelectorAll('.chip-btn[data-url]');
    const repoUrlInput = document.getElementById('repo-url');

    urlChips.forEach(chip => {
        chip.addEventListener('click', (e) => {
            e.preventDefault();
            const targetUrl = chip.getAttribute('data-url');
            if (repoUrlInput && targetUrl) {
                repoUrlInput.value = targetUrl;
                repoUrlInput.focus();
                repoUrlInput.classList.remove('input-error');
                hideFeedback('url-feedback');
            }
        });
    });

    // Keyword sample chips
    const keywordChips = document.querySelectorAll('.keyword-chip[data-keyword]');
    const keywordInput = document.getElementById('keyword-input');

    keywordChips.forEach(chip => {
        chip.addEventListener('click', async (e) => {
            e.preventDefault();
            const targetKeyword = chip.getAttribute('data-keyword');
            if (keywordInput && targetKeyword) {
                keywordInput.value = targetKeyword;
                keywordInput.classList.remove('input-error');
                hideFeedback('keyword-feedback');
                lastSearchKeyword = targetKeyword;
                await executeKeywordSearch(targetKeyword);
            }
        });
    });
}

/**
 * Display a modern toast notification.
 * @param {string} title
 * @param {string} message
 * @param {'info'|'success'|'error'} type
 */
function showToast(title, message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <div class="toast-content">
            <div class="toast-title">${escapeHtml(title)}</div>
            <div class="toast-message">${escapeHtml(message)}</div>
        </div>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

/**
 * Escape HTML string helper.
 * @param {string} str
 */
function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ==============================================================================
// Phase 5: Repository Acquisition & Codebase Analysis Controller
// ==============================================================================

let currentAnalysisData = null;
let activeCategoryFilter = 'all';
let activeSearchQuery = '';

/**
 * Initialize Phase 5 analysis page if elements exist.
 */
function initAnalysisPage() {
    const form = document.getElementById('analysis-form');
    if (!form) return; // Not on /analysis page

    loadCachedRepositories();

    // Check URL query parameters (e.g. /analysis?repo=pallets/flask)
    const urlParams = new URLSearchParams(window.location.search);
    const repoParam = urlParams.get('repo');
    if (repoParam) {
        const input = document.getElementById('analysis-repo-input');
        if (input) input.value = repoParam;
        runAnalysis(repoParam, false);
    }
}

/**
 * Fetch and display quick chips for all previously analyzed repositories.
 */
async function loadCachedRepositories() {
    const listEl = document.getElementById('cached-chips-list');
    const container = document.getElementById('cached-repos-chips');
    if (!listEl) return;

    try {
        const resp = await fetch('/api/repositories/analysis/cached');
        const data = await resp.json();
        if (data.success && data.repositories && data.repositories.length > 0) {
            listEl.innerHTML = '';
            data.repositories.slice(0, 5).forEach(r => {
                const chip = document.createElement('button');
                chip.type = 'button';
                chip.className = 'cached-chip';
                chip.textContent = `${r.full_name} (${r.total_files} files)`;
                chip.addEventListener('click', () => {
                    const input = document.getElementById('analysis-repo-input');
                    if (input) input.value = r.full_name;
                    runAnalysis(r.full_name, false);
                });
                listEl.appendChild(chip);
            });
            if (container) container.style.display = 'flex';
        } else {
            if (container) container.style.display = 'none';
        }
    } catch (err) {
        console.warn('[CodeLens AI] Could not load cached repositories:', err);
    }
}

/**
 * Trigger analysis from the main search form on /analysis.
 */
function triggerAnalysis() {
    const input = document.getElementById('analysis-repo-input');
    const chk = document.getElementById('force-refresh-checkbox');
    const repo = input ? input.value.trim() : '';
    const force = chk ? chk.checked : false;

    if (!repo) {
        showAnalysisAlert('Please enter a repository owner/name or GitHub URL.', 'error');
        return;
    }

    runAnalysis(repo, force);
}

/**
 * Trigger re-analysis for current active repository.
 */
function triggerReanalysis() {
    if (currentAnalysisData && currentAnalysisData.repository) {
        runAnalysis(currentAnalysisData.repository.full_name, true);
    }
}

/**
 * Quick fill helper for sample repositories.
 * @param {string} repo
 */
function loadSampleRepo(repo) {
    const input = document.getElementById('analysis-repo-input');
    if (input) input.value = repo;
    runAnalysis(repo, false);
}

/**
 * Perform repository acquisition and static analysis.
 * @param {string} repoInput
 * @param {boolean} forceRefresh
 */
async function runAnalysis(repoInput, forceRefresh = false) {
    const loadingView = document.getElementById('analysis-loading-view');
    const emptyView = document.getElementById('analysis-empty-view');
    const resultsContainer = document.getElementById('analysis-results-container');
    const btnTrigger = document.getElementById('btn-trigger-analysis');
    const stageTitle = document.getElementById('loading-stage-title');
    const stageDesc = document.getElementById('loading-stage-desc');

    hideAnalysisAlert();

    if (emptyView) emptyView.style.display = 'none';
    if (resultsContainer) resultsContainer.style.display = 'none';
    if (loadingView) loadingView.style.display = 'flex';

    if (btnTrigger) btnTrigger.disabled = true;

    if (stageTitle) stageTitle.textContent = forceRefresh ? 'Re-cloning Repository...' : 'Acquiring Repository Safely...';
    if (stageDesc) stageDesc.textContent = 'Performing shallow Git clone into local workspace. No code is executed.';

    try {
        const response = await fetch('/api/repositories/acquire-and-analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                repo: repoInput,
                force_refresh: forceRefresh,
            }),
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to acquire and analyze repository.');
        }

        currentAnalysisData = data;
        renderAnalysisDashboard(data);

        // Update URL query param cleanly without full reload
        const newUrl = `${window.location.pathname}?repo=${encodeURIComponent(data.repository.full_name)}`;
        window.history.pushState({ path: newUrl }, '', newUrl);

        if (loadingView) loadingView.style.display = 'none';
        if (resultsContainer) {
            resultsContainer.style.display = 'flex';
            resultsContainer.style.flexDirection = 'column';
            resultsContainer.style.width = '100%';
        }

        // Refresh cached repos list
        loadCachedRepositories();

        showToast(
            'Analysis Complete',
            `Analyzed ${data.repository.full_name} (${data.statistics.total_files} files scanned)`,
            'success'
        );

        // Automatically trigger Phase 6 Deep AST Analysis
        triggerAstAnalysis(false);

    } catch (err) {
        console.error('[CodeLens AI] Analysis error:', err);
        if (loadingView) loadingView.style.display = 'none';
        if (emptyView) emptyView.style.display = 'block';
        showAnalysisAlert(err.message || 'An error occurred during repository analysis.', 'error');
    } finally {
        if (btnTrigger) btnTrigger.disabled = false;
    }
}

let activeAnalysisFeature = 'all';

/**
 * Switch view to focus on a single feature or view all features separated.
 * @param {'all'|'overview'|'languages'|'files'|'ast'|'graph'|'json'} feature
 * @param {HTMLElement} btnEl
 */
function switchAnalysisFeature(feature, btnEl) {
    activeAnalysisFeature = feature;
    document.querySelectorAll('.analysis-feature-nav .feature-nav-btn').forEach(b => b.classList.remove('active'));
    if (btnEl) btnEl.classList.add('active');

    const metricsSec = document.getElementById('section-metrics');
    const langSec = document.getElementById('section-languages');
    const explorerSec = document.getElementById('section-explorer');
    const astSec = document.getElementById('ast-analysis-section');
    const graphSec = document.getElementById('semantic-graph-section');
    const jsonSec = document.getElementById('section-json');

    const allBlocks = [
        { name: 'overview', el: metricsSec, displayType: 'grid' },
        { name: 'languages', el: langSec, displayType: 'block' },
        { name: 'files', el: explorerSec, displayType: 'block' },
        { name: 'ast', el: astSec, displayType: 'block' },
        { name: 'graph', el: graphSec, displayType: 'block' },
        { name: 'json', el: jsonSec, displayType: 'block' }
    ];

    if (feature === 'all') {
        allBlocks.forEach(b => {
            if (b.el) b.el.style.display = b.displayType;
        });
    } else {
        allBlocks.forEach(b => {
            if (!b.el) return;
            if (b.name === feature) {
                b.el.style.display = b.displayType;
                b.el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            } else {
                b.el.style.display = 'none';
            }
        });
    }

    // Refresh canvas dimensions if graph tab is selected
    if (feature === 'graph' || feature === 'all') {
        setTimeout(() => {
            if (typeof resetGraphView === 'function') resetGraphView();
        }, 60);
    }
}

/**
 * Render the entire Phase 5 analysis dashboard with acquired metrics.
 * @param {object} data
 */
function renderAnalysisDashboard(data) {
    const repo = data.repository || {};
    const stats = data.statistics || {};
    const languages = data.languages || {};
    const files = data.files || [];
    const tree = data.directory_tree || {};

    // 1. Repo Header Card
    const nameEl = document.getElementById('repo-full-name');
    const badgeCache = document.getElementById('repo-badge-cache');
    const linkEl = document.getElementById('repo-github-link');
    const pathEl = document.getElementById('repo-local-path');
    const timeEl = document.getElementById('repo-acquired-time');
    const langEl = document.getElementById('repo-primary-lang');

    if (nameEl) nameEl.textContent = repo.full_name || `${repo.owner}/${repo.name}`;
    if (linkEl) linkEl.href = repo.url || `https://github.com/${repo.full_name}`;
    const exploreBtn = document.getElementById('btn-explore-arch');
    const bannerExploreBtn = document.getElementById('banner-explore-arch');
    const navArchBtn = document.getElementById('nav-btn-architecture');
    const reportBtn = document.getElementById('btn-view-report');
    const navReportBtn = document.getElementById('nav-btn-report');
    const chatBtn = document.getElementById('btn-chat-analysis');
    const fullRepoName = repo.full_name || `${repo.owner}/${repo.name}`;
    if (exploreBtn) exploreBtn.href = `/architecture?repo=${encodeURIComponent(fullRepoName)}`;
    if (bannerExploreBtn) bannerExploreBtn.href = `/architecture?repo=${encodeURIComponent(fullRepoName)}`;
    if (navArchBtn) navArchBtn.href = `/architecture?repo=${encodeURIComponent(fullRepoName)}`;
    if (reportBtn) reportBtn.href = `/report?repo=${encodeURIComponent(fullRepoName)}`;
    if (navReportBtn) navReportBtn.href = `/report?repo=${encodeURIComponent(fullRepoName)}`;
    if (chatBtn) chatBtn.href = `/chat?repo=${encodeURIComponent(fullRepoName)}`;
    if (pathEl) pathEl.textContent = repo.local_path || 'data/repositories/...';
    if (timeEl) {
        const d = repo.acquired_at ? new Date(repo.acquired_at) : new Date();
        timeEl.textContent = d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    if (badgeCache) {
        if (data.is_cached) {
            badgeCache.textContent = 'Local Cache';
            badgeCache.className = 'badge badge-success';
        } else {
            badgeCache.textContent = 'Fresh Clone';
            badgeCache.className = 'badge badge-info';
        }
    }
    if (langEl) langEl.textContent = stats.primary_language || 'Not specified';

    // 2. 5 Stats Cards
    const totalFilesEl = document.getElementById('stat-total-files');
    const totalDirsEl = document.getElementById('stat-total-dirs');
    const sourceFilesEl = document.getElementById('stat-source-files');
    const sourcePctEl = document.getElementById('stat-source-pct');
    const otherFilesEl = document.getElementById('stat-other-files');
    const docsConfigEl = document.getElementById('stat-docs-config');
    const totalSizeEl = document.getElementById('stat-total-size');

    if (totalFilesEl) totalFilesEl.textContent = Number(stats.total_files || 0).toLocaleString();
    if (totalDirsEl) totalDirsEl.textContent = Number(stats.total_directories || 0).toLocaleString();
    if (sourceFilesEl) sourceFilesEl.textContent = Number(stats.source_files || 0).toLocaleString();

    if (sourcePctEl) {
        const pct = stats.total_files > 0 ? Math.round((stats.source_files / stats.total_files) * 100) : 0;
        sourcePctEl.textContent = `${pct}% of total files`;
    }

    if (otherFilesEl) otherFilesEl.textContent = Number(stats.other_files + (stats.doc_files || 0) + (stats.config_files || 0)).toLocaleString();
    if (docsConfigEl) docsConfigEl.textContent = `${stats.doc_files || 0} docs, ${stats.config_files || 0} configs`;
    if (totalSizeEl) totalSizeEl.textContent = stats.total_size_formatted || '0 KB';

    // 3. Languages Section
    renderLanguageDistribution(languages);

    // 4. Directory Tree
    renderDirectoryTree(tree, stats.total_directories, stats.total_files);

    // 5. Files Table
    renderFilesTable(files);

    // 6. JSON Export Preview
    const jsonPreview = document.getElementById('analysis-json-preview');
    if (jsonPreview) {
        jsonPreview.innerHTML = `<code>${escapeHtml(JSON.stringify(data, null, 2))}</code>`;
    }
}

/**
 * Palette mapping for programming language indicators.
 */
function getLanguageColor(lang) {
    const colors = {
        'Python': '#3572A5',
        'JavaScript': '#f1e05a',
        'TypeScript': '#3178c6',
        'HTML': '#e34c26',
        'CSS': '#563d7c',
        'SCSS': '#c6538c',
        'C': '#555555',
        'C++': '#f34b7d',
        'C#': '#178600',
        'Go': '#00ADD8',
        'Rust': '#dea584',
        'Java': '#b07219',
        'Kotlin': '#A97BFF',
        'Swift': '#F05138',
        'Ruby': '#701516',
        'PHP': '#4F5D95',
        'Shell': '#89e051',
        'Bash': '#89e051',
        'SQL': '#e38c00',
        'Lua': '#000080',
        'R': '#198CE7',
        'Dart': '#00B4AB',
    };
    return colors[lang] || '#64748b';
}

/**
 * Render multi-color stacked distribution bar and language cards.
 * @param {object} languages
 */
function renderLanguageDistribution(languages) {
    const bar = document.getElementById('language-bar-container');
    const grid = document.getElementById('languages-grid');
    const countBadge = document.getElementById('lang-count-badge');

    if (!bar || !grid) return;

    bar.innerHTML = '';
    grid.innerHTML = '';

    const entries = Object.entries(languages);
    if (countBadge) countBadge.textContent = `${entries.length} Detected`;

    if (entries.length === 0) {
        grid.innerHTML = '<p class="text-muted">No primary programming language source files detected.</p>';
        return;
    }

    entries.forEach(([lang, info]) => {
        const color = getLanguageColor(lang);

        // Segment in stacked bar
        const seg = document.createElement('div');
        seg.className = 'lang-bar-segment';
        seg.style.width = `${info.percentage}%`;
        seg.style.backgroundColor = color;
        seg.title = `${lang}: ${info.percentage}% (${info.files_count} files, ${info.size_formatted})`;
        bar.appendChild(seg);

        // Card in grid
        const card = document.createElement('div');
        card.className = 'language-card';
        card.innerHTML = `
            <div class="lang-card-left">
                <span class="lang-dot" style="background-color: ${color}"></span>
                <div>
                    <div class="lang-name">${escapeHtml(lang)}</div>
                    <div class="lang-meta">${info.files_count} files • ${info.size_formatted}</div>
                </div>
            </div>
            <div class="lang-pct">${info.percentage}%</div>
        `;
        grid.appendChild(card);
    });
}

/**
 * Render interactive directory tree hierarchy.
 * @param {object} rootNode
 * @param {number} totalDirs
 * @param {number} totalFiles
 */
function renderDirectoryTree(rootNode, totalDirs, totalFiles) {
    const rootEl = document.getElementById('directory-tree-root');
    const counterEl = document.getElementById('tree-node-counter');
    if (!rootEl) return;

    rootEl.innerHTML = '';
    if (counterEl) {
        counterEl.textContent = `${totalDirs} directories • ${totalFiles} files`;
    }

    if (!rootNode || !rootNode.children || rootNode.children.length === 0) {
        rootEl.innerHTML = '<p class="text-muted">Empty repository tree.</p>';
        return;
    }

    const treeFragment = document.createDocumentFragment();
    rootNode.children.forEach(child => {
        treeFragment.appendChild(createTreeNodeElement(child, 0));
    });
    rootEl.appendChild(treeFragment);
}

/**
 * Recursive creation of directory tree node elements.
 */
function createTreeNodeElement(node, depth = 0) {
    const itemEl = document.createElement('div');
    itemEl.className = `tree-item ${node.type === 'directory' ? 'tree-folder' : 'tree-file'}`;

    const labelEl = document.createElement('div');
    labelEl.className = 'tree-item-label';

    if (node.type === 'directory') {
        labelEl.innerHTML = `
            <span class="tree-folder-icon">📁</span>
            <span class="tree-name">${escapeHtml(node.name)}/</span>
        `;

        itemEl.appendChild(labelEl);

        const childrenEl = document.createElement('div');
        childrenEl.className = 'tree-children';

        // Auto collapse deeper directories (depth >= 1)
        if (depth >= 1) {
            childrenEl.classList.add('collapsed');
        }

        if (node.children && node.children.length > 0) {
            node.children.forEach(child => {
                childrenEl.appendChild(createTreeNodeElement(child, depth + 1));
            });
        }
        itemEl.appendChild(childrenEl);

        // Click to toggle folder
        labelEl.addEventListener('click', (e) => {
            e.stopPropagation();
            const isCollapsed = childrenEl.classList.toggle('collapsed');
            const icon = labelEl.querySelector('.tree-folder-icon');
            if (icon) icon.textContent = isCollapsed ? '📁' : '📂';
        });

    } else {
        const icon = getFileIcon(node.extension);
        labelEl.innerHTML = `
            <span class="tree-file-icon">${icon}</span>
            <span class="tree-name">${escapeHtml(node.name)}</span>
            <span class="tree-file-size">${node.size_formatted}</span>
        `;
        itemEl.appendChild(labelEl);
    }

    return itemEl;
}

function getFileIcon(ext) {
    if (!ext) return '📄';
    const lower = ext.toLowerCase();
    if (['.py', '.pyw'].includes(lower)) return '🐍';
    if (['.js', '.mjs', '.jsx'].includes(lower)) return '📜';
    if (['.ts', '.tsx'].includes(lower)) return '📘';
    if (['.html', '.htm'].includes(lower)) return '🌐';
    if (['.css', '.scss', '.less'].includes(lower)) return '🎨';
    if (['.md', '.markdown', '.rst', '.txt'].includes(lower)) return '📝';
    if (['.json', '.yaml', '.yml', '.toml'].includes(lower)) return '⚙️';
    if (['.c', '.cpp', '.h', '.hpp'].includes(lower)) return '⚡';
    if (['.go', '.rs'].includes(lower)) return '⚙️';
    return '📄';
}

function expandAllTree() {
    document.querySelectorAll('.tree-children').forEach(el => el.classList.remove('collapsed'));
    document.querySelectorAll('.tree-folder-icon').forEach(el => el.textContent = '📂');
}

function collapseAllTree() {
    document.querySelectorAll('.tree-children').forEach(el => el.classList.add('collapsed'));
    document.querySelectorAll('.tree-folder-icon').forEach(el => el.textContent = '📁');
}

/**
 * Switch tabs in explorer view (Directory Tree vs File Table).
 * @param {'tree'|'table'} tab
 */
function switchExplorerTab(tab) {
    const btnTree = document.getElementById('tab-btn-tree');
    const btnTable = document.getElementById('tab-btn-table');
    const tabTree = document.getElementById('tab-tree-view');
    const tabTable = document.getElementById('tab-table-view');

    if (tab === 'tree') {
        if (btnTree) btnTree.classList.add('active');
        if (btnTable) btnTable.classList.remove('active');
        if (tabTree) tabTree.classList.add('active');
        if (tabTable) tabTable.classList.remove('active');
    } else {
        if (btnTable) btnTable.classList.add('active');
        if (btnTree) btnTree.classList.remove('active');
        if (tabTable) tabTable.classList.add('active');
        if (tabTree) tabTree.classList.remove('active');
    }
}

/**
 * Filter files table by category.
 */
function filterByCategory(category, buttonEl) {
    activeCategoryFilter = category;
    document.querySelectorAll('.cat-pill').forEach(btn => btn.classList.remove('active'));
    if (buttonEl) buttonEl.classList.add('active');

    if (currentAnalysisData && currentAnalysisData.files) {
        renderFilesTable(currentAnalysisData.files);
    }
}

/**
 * Client-side search / filter files list.
 */
function filterFilesList(query) {
    activeSearchQuery = (query || '').toLowerCase().trim();
    if (currentAnalysisData && currentAnalysisData.files) {
        renderFilesTable(currentAnalysisData.files);
    }
}

/**
 * Render tabular list of files.
 * @param {Array} files
 */
function renderFilesTable(files) {
    const tbody = document.getElementById('files-table-body');
    const notice = document.getElementById('table-pagination-notice');
    if (!tbody) return;

    tbody.innerHTML = '';

    // Update counts on filter pills
    const allCount = files.length;
    const srcCount = files.filter(f => f.category === 'source').length;
    const docCount = files.filter(f => f.category === 'documentation').length;
    const cfgCount = files.filter(f => f.category === 'configuration').length;
    const othCount = files.filter(f => f.category === 'other').length;

    const cAll = document.getElementById('cat-count-all');
    const cSrc = document.getElementById('cat-count-source');
    const cDoc = document.getElementById('cat-count-docs');
    const cCfg = document.getElementById('cat-count-config');
    const cOth = document.getElementById('cat-count-other');

    if (cAll) cAll.textContent = allCount;
    if (cSrc) cSrc.textContent = srcCount;
    if (cDoc) cDoc.textContent = docCount;
    if (cCfg) cCfg.textContent = cfgCount;
    if (cOth) cOth.textContent = othCount;

    // Filter files
    let filtered = files;
    if (activeCategoryFilter !== 'all') {
        filtered = filtered.filter(f => f.category === activeCategoryFilter);
    }
    if (activeSearchQuery) {
        filtered = filtered.filter(f =>
            f.path.toLowerCase().includes(activeSearchQuery) ||
            f.name.toLowerCase().includes(activeSearchQuery) ||
            f.extension.toLowerCase().includes(activeSearchQuery) ||
            (f.language && f.language.toLowerCase().includes(activeSearchQuery))
        );
    }

    const MAX_SHOWN = 300;
    const displayList = filtered.slice(0, MAX_SHOWN);

    if (displayList.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" class="text-center text-muted" style="padding: 2rem;">No matching files found.</td></tr>`;
        if (notice) notice.textContent = '';
        return;
    }

    displayList.forEach(file => {
        const tr = document.createElement('tr');
        const badgeClass = file.category === 'source' ? 'file-badge-source' :
                           file.category === 'documentation' ? 'file-badge-doc' :
                           file.category === 'configuration' ? 'file-badge-config' : 'file-badge-other';

        tr.innerHTML = `
            <td class="file-path-cell">
                <span class="file-icon">${getFileIcon(file.extension)}</span>
                <strong>${escapeHtml(file.name)}</strong>
                <span class="text-muted" style="font-size: 0.75rem; margin-left: 0.5rem;">${escapeHtml(file.path)}</span>
            </td>
            <td>
                <span class="badge ${badgeClass}" style="font-size: 0.72rem;">${escapeHtml(file.category)}</span>
            </td>
            <td>
                ${file.language ? `<span class="badge badge-secondary" style="font-size: 0.72rem;">${escapeHtml(file.language)}</span>` : '<span class="text-muted">—</span>'}
            </td>
            <td style="font-family: monospace; font-size: 0.8rem;">
                ${escapeHtml(file.size_formatted)}
            </td>
        `;
        tbody.appendChild(tr);
    });

    if (notice) {
        if (filtered.length > MAX_SHOWN) {
            notice.textContent = `Showing first ${MAX_SHOWN} of ${filtered.length.toLocaleString()} matching files.`;
        } else {
            notice.textContent = `Showing all ${filtered.length.toLocaleString()} matching files.`;
        }
    }
}

/**
 * Copy structured analysis JSON to clipboard.
 */
function copyAnalysisJson() {
    if (!currentAnalysisData) return;
    const text = JSON.stringify(currentAnalysisData, null, 2);
    navigator.clipboard.writeText(text).then(() => {
        showToast('Copied to Clipboard', 'Structured analysis JSON copied to clipboard.', 'success');
    }).catch(() => {
        showToast('Clipboard Error', 'Could not copy to clipboard automatically.', 'error');
    });
}

function showAnalysisAlert(msg, type = 'error') {
    const el = document.getElementById('analysis-alert');
    if (el) {
        el.className = `analysis-alert ${type}`;
        el.textContent = msg;
        el.style.display = 'block';
    }
}

function hideAnalysisAlert() {
    const el = document.getElementById('analysis-alert');
    if (el) {
        el.style.display = 'none';
        el.textContent = '';
    }
}

// ==============================================================================
// Phase 6: Deep Static Code Analysis (AST) Controller
// ==============================================================================

let currentAstKnowledgeData = null;
let activeAstTab = 'classes';
let activeAstSearch = '';
let activeJsonView = 'knowledge';

/**
 * Trigger deep static AST analysis on the currently active repository.
 */
async function triggerAstAnalysis(forceRefresh = false) {
    const section = document.getElementById('ast-analysis-section');
    const loadingView = document.getElementById('ast-loading-view');
    const resultsView = document.getElementById('ast-results-view');
    const btnRun = document.getElementById('btn-run-ast');

    if (!section) return;

    const repoName = currentAnalysisData && currentAnalysisData.repository ? currentAnalysisData.repository.full_name : '';
    if (!repoName) {
        const input = document.getElementById('analysis-repo-input');
        if (input && input.value) {
            triggerAnalysis();
            return;
        }
        showToast('Repository Required', 'Please acquire a repository before extracting AST knowledge.', 'error');
        return;
    }

    if (loadingView) loadingView.style.display = 'flex';
    if (resultsView) resultsView.style.display = 'none';
    if (btnRun) btnRun.disabled = true;

    try {
        const response = await fetch('/api/repositories/ast-analysis', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                repo: repoName,
                force_refresh: forceRefresh,
            }),
        });

        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to extract AST knowledge.');
        }

        currentAstKnowledgeData = data;
        renderAstDashboard(data);

        if (loadingView) loadingView.style.display = 'none';
        if (resultsView) resultsView.style.display = 'block';

        showToast(
            'AST Analysis Complete',
            `Extracted ${data.statistics.classes_count} classes, ${data.statistics.functions_count} functions, ${data.statistics.dependencies_count || data.statistics.total_dependencies_count} dependencies.`,
            'success'
        );

        // Automatically trigger Phase 7 Semantic Code Graph Generation
        triggerGraphGeneration(false);

    } catch (err) {
        console.error('[CodeLens AI] AST Analysis Error:', err);
        if (loadingView) loadingView.style.display = 'none';
        showToast('AST Analysis Notice', err.message, 'info');
    } finally {
        if (btnRun) btnRun.disabled = false;
    }
}

/**
 * Render AST Dashboard: 6 metric cards, entity inspector, and JSON preview.
 * @param {object} data
 */
function renderAstDashboard(data) {
    const stats = data.statistics || {};

    // 1. Populate 6 Metric Cards
    const elFiles = document.getElementById('ast-stat-files');
    const elClasses = document.getElementById('ast-stat-classes');
    const elFuncs = document.getElementById('ast-stat-functions');
    const elMethods = document.getElementById('ast-stat-methods');
    const elImports = document.getElementById('ast-stat-imports');
    const elDeps = document.getElementById('ast-stat-deps');

    if (elFiles) elFiles.textContent = Number(stats.source_files || 0).toLocaleString();
    if (elClasses) elClasses.textContent = Number(stats.classes_count || 0).toLocaleString();
    if (elFuncs) elFuncs.textContent = Number(stats.functions_count || 0).toLocaleString();
    if (elMethods) elMethods.textContent = Number(stats.methods_count || 0).toLocaleString();
    if (elImports) elImports.textContent = Number(stats.imports_count || 0).toLocaleString();
    if (elDeps) elDeps.textContent = Number(stats.external_dependencies_count || stats.total_dependencies_count || 0).toLocaleString();

    // 2. Populate Tab Counts
    const tabCls = document.getElementById('ast-tab-count-classes');
    const tabFunc = document.getElementById('ast-tab-count-functions');
    const tabMeth = document.getElementById('ast-tab-count-methods');
    const tabDeps = document.getElementById('ast-tab-count-deps');
    const tabRels = document.getElementById('ast-tab-count-rels');
    const tabEntry = document.getElementById('ast-tab-count-entry');

    if (tabCls) tabCls.textContent = (data.classes || []).length;
    if (tabFunc) tabFunc.textContent = (data.functions || []).length;
    if (tabMeth) tabMeth.textContent = (data.methods || []).length;
    if (tabDeps) tabDeps.textContent = (data.dependencies || []).length;
    if (tabRels) tabRels.textContent = (data.relationships || []).length;
    if (tabEntry) tabEntry.textContent = (data.entry_points || []).length;

    // 3. Render Active Entity Tab
    renderAstEntities();

    // 4. Update JSON preview
    toggleJsonView(activeJsonView);
}

/**
 * Switch tabs in the Entity Inspector.
 */
function switchAstTab(tabName, btnEl) {
    activeAstTab = tabName;
    document.querySelectorAll('.ast-tab-btn').forEach(btn => btn.classList.remove('active'));
    if (btnEl) btnEl.classList.add('active');

    document.querySelectorAll('.ast-tab-pane').forEach(pane => pane.classList.remove('active'));
    const targetPane = document.getElementById(`ast-content-${tabName}`);
    if (targetPane) targetPane.classList.add('active');

    renderAstEntities();
}

/**
 * Live filter for extracted AST entities.
 */
function filterAstEntities(query) {
    activeAstSearch = (query || '').toLowerCase().trim();
    renderAstEntities();
}

/**
 * Render entities for the currently active tab.
 */
function renderAstEntities() {
    if (!currentAstKnowledgeData) return;

    if (activeAstTab === 'classes') {
        renderClassesList(currentAstKnowledgeData.classes || []);
    } else if (activeAstTab === 'functions') {
        renderFunctionsList(currentAstKnowledgeData.functions || []);
    } else if (activeAstTab === 'methods') {
        renderMethodsList(currentAstKnowledgeData.methods || []);
    } else if (activeAstTab === 'dependencies') {
        renderDependenciesList(currentAstKnowledgeData.dependencies || []);
    } else if (activeAstTab === 'relationships') {
        renderRelationshipsList(currentAstKnowledgeData.relationships || []);
    } else if (activeAstTab === 'entry_points') {
        renderEntryPointsList(currentAstKnowledgeData.entry_points || []);
    }
}

/**
 * Render Classes entity cards.
 */
function renderClassesList(classes) {
    const container = document.getElementById('ast-classes-list');
    if (!container) return;

    let filtered = classes;
    if (activeAstSearch) {
        filtered = filtered.filter(c =>
            c.name.toLowerCase().includes(activeAstSearch) ||
            c.file.toLowerCase().includes(activeAstSearch) ||
            (c.bases && c.bases.some(b => b.toLowerCase().includes(activeAstSearch)))
        );
    }

    if (filtered.length === 0) {
        container.innerHTML = '<p class="text-muted" style="padding: 1.5rem;">No matching classes found.</p>';
        return;
    }

    container.innerHTML = filtered.slice(0, 150).map(c => `
        <div class="ast-card-item">
            <div class="ast-card-top">
                <span class="ast-card-title">${escapeHtml(c.name)}</span>
                <span class="badge badge-info" style="font-size: 0.7rem;">${escapeHtml(c.language || 'Class')}</span>
            </div>
            <div class="ast-card-file">📄 ${escapeHtml(c.file)}${c.line_start ? `:${c.line_start}` : ''}</div>
            
            <div class="ast-meta-pills">
                ${c.bases && c.bases.length > 0 ? c.bases.map(b => `<span class="ast-pill ast-pill-base">inherits: ${escapeHtml(b)}</span>`).join('') : '<span class="ast-pill ast-pill-base">base: object</span>'}
                <span class="ast-pill ast-pill-arg">${c.methods_count || 0} methods</span>
            </div>

            ${c.docstring ? `<div class="ast-card-doc">"${escapeHtml(c.docstring)}"</div>` : ''}
        </div>
    `).join('');
}

/**
 * Render Functions entity cards.
 */
function renderFunctionsList(functions) {
    const container = document.getElementById('ast-functions-list');
    if (!container) return;

    let filtered = functions;
    if (activeAstSearch) {
        filtered = filtered.filter(f =>
            f.name.toLowerCase().includes(activeAstSearch) ||
            f.file.toLowerCase().includes(activeAstSearch)
        );
    }

    if (filtered.length === 0) {
        container.innerHTML = '<p class="text-muted" style="padding: 1.5rem;">No matching functions found.</p>';
        return;
    }

    container.innerHTML = filtered.slice(0, 150).map(f => `
        <div class="ast-card-item">
            <div class="ast-card-top">
                <span class="ast-card-title">${f.is_async ? 'async ' : ''}${escapeHtml(f.name)}()</span>
                <span class="badge badge-secondary" style="font-size: 0.7rem;">Function</span>
            </div>
            <div class="ast-card-file">📄 ${escapeHtml(f.file)}${f.line_start ? `:${f.line_start}` : ''}</div>

            <div class="ast-meta-pills">
                ${f.args && f.args.length > 0 ? f.args.map(a => `<span class="ast-pill ast-pill-arg">${escapeHtml(a)}</span>`).join('') : '<span class="ast-pill ast-pill-arg">no params</span>'}
                ${f.decorators && f.decorators.length > 0 ? f.decorators.map(d => `<span class="ast-pill ast-pill-dec">@${escapeHtml(d)}</span>`).join('') : ''}
            </div>

            ${f.docstring ? `<div class="ast-card-doc">"${escapeHtml(f.docstring)}"</div>` : ''}
        </div>
    `).join('');
}

/**
 * Render Methods entity cards.
 */
function renderMethodsList(methods) {
    const container = document.getElementById('ast-methods-list');
    if (!container) return;

    let filtered = methods;
    if (activeAstSearch) {
        filtered = filtered.filter(m =>
            m.name.toLowerCase().includes(activeAstSearch) ||
            (m.class_name && m.class_name.toLowerCase().includes(activeAstSearch)) ||
            m.file.toLowerCase().includes(activeAstSearch)
        );
    }

    if (filtered.length === 0) {
        container.innerHTML = '<p class="text-muted" style="padding: 1.5rem;">No matching methods found.</p>';
        return;
    }

    container.innerHTML = filtered.slice(0, 150).map(m => `
        <div class="ast-card-item">
            <div class="ast-card-top">
                <span class="ast-card-title">${escapeHtml(m.class_name ? m.class_name + '.' : '')}${escapeHtml(m.name)}()</span>
                <span class="badge badge-primary" style="font-size: 0.7rem;">Method</span>
            </div>
            <div class="ast-card-file">📄 ${escapeHtml(m.file)}${m.line_start ? `:${m.line_start}` : ''}</div>

            <div class="ast-meta-pills">
                ${m.args && m.args.length > 0 ? m.args.map(a => `<span class="ast-pill ast-pill-arg">${escapeHtml(a)}</span>`).join('') : '<span class="ast-pill ast-pill-arg">no params</span>'}
                ${m.modifiers && m.modifiers.length > 0 ? m.modifiers.map(mod => `<span class="ast-pill ast-pill-dec">${escapeHtml(mod)}</span>`).join('') : ''}
            </div>

            ${m.docstring ? `<div class="ast-card-doc">"${escapeHtml(m.docstring)}"</div>` : ''}
        </div>
    `).join('');
}

/**
 * Render Dependencies entity cards.
 */
function renderDependenciesList(dependencies) {
    const container = document.getElementById('ast-deps-list');
    if (!container) return;

    let filtered = dependencies;
    if (activeAstSearch) {
        filtered = filtered.filter(d => d.name.toLowerCase().includes(activeAstSearch));
    }

    if (filtered.length === 0) {
        container.innerHTML = '<p class="text-muted" style="padding: 1.5rem;">No dependencies detected.</p>';
        return;
    }

    container.innerHTML = filtered.map(d => `
        <div class="ast-card-item">
            <div class="ast-card-top">
                <span class="ast-card-title">📦 ${escapeHtml(d.name)}</span>
                <span class="badge ${d.is_standard_library ? 'badge-success' : 'badge-warning'}" style="font-size: 0.7rem;">
                    ${d.is_standard_library ? 'Standard Library' : 'External Third-Party'}
                </span>
            </div>
            <div class="ast-meta-pills">
                <span class="ast-pill ${d.is_standard_library ? 'ast-pill-std' : 'ast-pill-ext'}">${d.occurrences} import statements</span>
                <span class="ast-pill ast-pill-arg">${d.files_count || (d.files ? d.files.length : 0)} files</span>
            </div>
            ${d.files && d.files.length > 0 ? `
                <div class="ast-card-file" style="margin-top: 0.4rem;">
                    Used in: ${d.files.slice(0, 3).map(f => escapeHtml(f)).join(', ')}${d.files.length > 3 ? '...' : ''}
                </div>
            ` : ''}
        </div>
    `).join('');
}

/**
 * Render Relationships table.
 */
function renderRelationshipsList(relationships) {
    const tbody = document.getElementById('ast-rels-tbody');
    if (!tbody) return;

    let filtered = relationships;
    if (activeAstSearch) {
        filtered = filtered.filter(r =>
            r.source.toLowerCase().includes(activeAstSearch) ||
            r.relation.toLowerCase().includes(activeAstSearch) ||
            r.target.toLowerCase().includes(activeAstSearch)
        );
    }

    if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted" style="padding: 1.5rem;">No relationships found.</td></tr>';
        return;
    }

    tbody.innerHTML = filtered.slice(0, 200).map(r => `
        <tr>
            <td style="font-family: monospace; font-size: 0.8rem; font-weight: 600;">${escapeHtml(r.source)}</td>
            <td>
                <span class="badge badge-info" style="font-size: 0.72rem;">${escapeHtml(r.relation)}</span>
            </td>
            <td style="font-family: monospace; font-size: 0.8rem; color: #2563eb;">${escapeHtml(r.target)}</td>
            <td class="text-muted" style="font-size: 0.75rem;">
                ${escapeHtml(r.source_type || 'entity')} → ${escapeHtml(r.target_type || 'entity')}
            </td>
        </tr>
    `).join('');
}

/**
 * Render Entry Points entity cards.
 */
function renderEntryPointsList(entryPoints) {
    const container = document.getElementById('ast-entry-list');
    if (!container) return;

    if (entryPoints.length === 0) {
        container.innerHTML = '<p class="text-muted" style="padding: 1.5rem;">No execution entry points detected.</p>';
        return;
    }

    container.innerHTML = entryPoints.map(e => `
        <div class="ast-card-item">
            <div class="ast-card-top">
                <span class="ast-card-title">🚀 ${escapeHtml(e.symbol || e.type)}</span>
                <span class="badge badge-success" style="font-size: 0.7rem;">Entry Point</span>
            </div>
            <div class="ast-card-file">📄 ${escapeHtml(e.file)}${e.line ? `:${e.line}` : ''}</div>
            <div class="ast-meta-pills">
                <span class="ast-pill ast-pill-dec">type: ${escapeHtml(e.type)}</span>
            </div>
        </div>
    `).join('');
}

/**
 * Toggle between Phase 5 File Scan, Phase 6 AST Knowledge, and Phase 7 Code Graph JSON preview.
 */
function toggleJsonView(viewType) {
    activeJsonView = viewType;
    const jsonPreview = document.getElementById('analysis-json-preview');
    if (!jsonPreview) return;

    document.querySelectorAll('.json-export-actions .btn-xs').forEach(btn => btn.classList.remove('active'));

    const clickedBtn = Array.from(document.querySelectorAll('.json-export-actions .btn-xs')).find(b =>
        (viewType === 'analysis' && b.textContent.includes('Phase 5')) ||
        (viewType === 'knowledge' && b.textContent.includes('Phase 6')) ||
        (viewType === 'graph' && b.textContent.includes('Phase 7'))
    );
    if (clickedBtn) clickedBtn.classList.add('active');

    if (viewType === 'graph' && currentGraphData) {
        jsonPreview.innerHTML = `<code>${escapeHtml(JSON.stringify(currentGraphData, null, 2))}</code>`;
    } else if (viewType === 'knowledge' && currentAstKnowledgeData) {
        jsonPreview.innerHTML = `<code>${escapeHtml(JSON.stringify(currentAstKnowledgeData, null, 2))}</code>`;
    } else if (currentAnalysisData) {
        jsonPreview.innerHTML = `<code>${escapeHtml(JSON.stringify(currentAnalysisData, null, 2))}</code>`;
    }
}

// ==============================================================================
// Phase 7: Semantic Code Graph Controller & Canvas Visualization
// ==============================================================================

let currentGraphData = null;
let activeGraphFilter = 'all';
let selectedGraphNode = null;
let graphNodes = [];
let graphEdges = [];
let graphCamera = { x: 0, y: 0, scale: 0.85 };
let isGraphDragging = false;
let graphDragStart = { x: 0, y: 0 };
let hoveredGraphNode = null;
let graphAnimationId = null;

const NODE_COLORS = {
    repository: '#eab308',  // Gold
    directory:  '#94a3b8',  // Slate
    file:       '#3b82f6',  // Blue
    class:      '#a855f7',  // Purple
    function:   '#10b981',  // Green
    method:     '#06b6d4',  // Cyan
    dependency: '#f97316',  // Orange
};

const EDGE_COLORS = {
    CONTAINS:   '#64748b',
    INHERITS:   '#a855f7',
    IMPORTS:    '#10b981',
    DEFINES:    '#f59e0b',
    DEPENDS_ON: '#ef4444',
    CALLS:      '#ec4899',
};

/**
 * Trigger Semantic Code Graph Generation via REST API.
 * @param {boolean} forceRefresh
 */
async function triggerGraphGeneration(forceRefresh = false) {
    if (!currentAnalysisData || !currentAnalysisData.repository) return;

    const repo = currentAnalysisData.repository;
    const loadingEl = document.getElementById('graph-loading');
    const dashboardEl = document.getElementById('graph-dashboard');
    const cachedBadge = document.getElementById('graph-cached-badge');

    if (loadingEl) loadingEl.style.display = 'block';
    if (dashboardEl) dashboardEl.style.opacity = '0.5';

    try {
        const response = await fetch('/api/repositories/graph', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                owner: repo.owner,
                name: repo.name,
                force_refresh: forceRefresh,
            }),
        });

        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to construct Semantic Code Graph.');
        }

        currentGraphData = data.graph;

        if (cachedBadge) {
            cachedBadge.textContent = data.is_cached ? 'Cached' : 'Computed';
            cachedBadge.className = `badge ${data.is_cached ? 'badge-primary' : 'badge-success'}`;
        }

        renderGraphDashboard(data.graph);
        initSemanticGraphCanvas(data.graph);

        showToast(
            'Code Graph Ready',
            `Constructed Semantic Code Graph with ${data.graph.statistics.total_nodes} nodes and ${data.graph.statistics.total_edges} edges.`,
            'success'
        );

    } catch (err) {
        console.error('[CodeLens AI] Graph Error:', err);
        showToast('Graph Notice', err.message, 'info');
    } finally {
        if (loadingEl) loadingEl.style.display = 'none';
        if (dashboardEl) dashboardEl.style.opacity = '1';
    }
}

/**
 * Render Graph Statistics Cards.
 * @param {object} graph
 */
function renderGraphDashboard(graph) {
    const stats = graph.statistics || {};

    const elNodes = document.getElementById('graph-stat-nodes');
    const elEdges = document.getElementById('graph-stat-edges');
    const elFiles = document.getElementById('graph-stat-files');
    const elClasses = document.getElementById('graph-stat-classes');
    const elFuncs = document.getElementById('graph-stat-functions');
    const elMethods = document.getElementById('graph-stat-methods');

    if (elNodes) elNodes.textContent = Number(stats.total_nodes || 0).toLocaleString();
    if (elEdges) elEdges.textContent = Number(stats.total_edges || 0).toLocaleString();
    if (elFiles) elFiles.textContent = Number(stats.file_nodes || 0).toLocaleString();
    if (elClasses) elClasses.textContent = Number(stats.class_nodes || 0).toLocaleString();
    if (elFuncs) elFuncs.textContent = Number(stats.function_nodes || 0).toLocaleString();
    if (elMethods) elMethods.textContent = Number(stats.method_nodes || 0).toLocaleString();

    // Update JSON preview if graph tab is active
    if (activeJsonView === 'graph') {
        toggleJsonView('graph');
    }
}

/**
 * Initialize Canvas Force Layout and Event Listeners.
 * @param {object} graph
 */
function initSemanticGraphCanvas(graph) {
    const canvas = document.getElementById('graph-canvas');
    const container = document.getElementById('graph-canvas-container');
    if (!canvas || !container) return;

    // Resize canvas to container
    const width = container.clientWidth || 800;
    const height = container.clientHeight || 540;
    canvas.width = width;
    canvas.height = height;

    const rawNodes = graph.nodes || [];
    const rawEdges = graph.edges || [];

    // Map nodes with positions and visual properties
    const nodeMap = new Map();
    const typeRadius = {
        repository: 16,
        directory: 12,
        file: 9,
        class: 8,
        function: 7,
        method: 6,
        dependency: 8,
    };

    // Cap node display to 350 nodes for smooth 60fps performance if repo is very large
    const displayNodes = rawNodes.slice(0, 350);
    const validIds = new Set(displayNodes.map(n => n.id));

    displayNodes.forEach((n, idx) => {
        // Initial layout: concentric circular clusters
        let angle = (idx / displayNodes.length) * Math.PI * 2;
        let dist = 120;
        if (n.type === 'repository') { dist = 0; }
        else if (n.type === 'directory') { dist = 90 + (idx % 4) * 25; }
        else if (n.type === 'file') { dist = 180 + (idx % 6) * 20; }
        else if (n.type === 'class') { dist = 260 + (idx % 5) * 20; }
        else if (n.type === 'function') { dist = 320 + (idx % 6) * 15; }
        else if (n.type === 'method') { dist = 380 + (idx % 6) * 15; }
        else if (n.type === 'dependency') { dist = 430 + (idx % 4) * 20; }

        const nodeObj = {
            ...n,
            x: Math.cos(angle) * dist,
            y: Math.sin(angle) * dist,
            vx: 0,
            vy: 0,
            radius: typeRadius[n.type] || 7,
            color: NODE_COLORS[n.type] || '#94a3b8',
        };
        nodeMap.set(n.id, nodeObj);
    });

    graphNodes = Array.from(nodeMap.values());

    // Filter edges to only those between displayed nodes
    graphEdges = rawEdges.filter(e => validIds.has(e.source) && validIds.has(e.target)).map(e => ({
        ...e,
        sourceNode: nodeMap.get(e.source),
        targetNode: nodeMap.get(e.target),
        color: EDGE_COLORS[e.type] || '#64748b',
    })).filter(e => e.sourceNode && e.targetNode);

    // Initial camera position centered
    graphCamera = {
        x: width / 2,
        y: height / 2,
        scale: 0.85,
    };

    // Run simple spring relaxation simulation (40 steps)
    for (let step = 0; step < 40; step++) {
        simulateGraphStep();
    }

    // Attach event listeners (pan, zoom, hover, click)
    setupCanvasInteractions(canvas);

    // Start render loop
    requestAnimationFrame(renderCanvasGraph);
}

/**
 * Physics relaxation step (repulsion + spring attraction).
 */
function simulateGraphStep() {
    const kRepel = 600;
    const kSpring = 0.04;
    const damping = 0.85;

    // Repulsion between nodes
    for (let i = 0; i < graphNodes.length; i++) {
        for (let j = i + 1; j < graphNodes.length; j++) {
            const n1 = graphNodes[i];
            const n2 = graphNodes[j];
            const dx = n2.x - n1.x;
            const dy = n2.y - n1.y;
            const distSq = dx * dx + dy * dy + 10;
            const dist = Math.sqrt(distSq);
            if (dist < 220) {
                const force = kRepel / distSq;
                const fx = (dx / dist) * force;
                const fy = (dy / dist) * force;
                n1.vx -= fx;
                n1.vy -= fy;
                n2.vx += fx;
                n2.vy += fy;
            }
        }
    }

    // Attraction along edges
    for (const e of graphEdges) {
        const u = e.sourceNode;
        const v = e.targetNode;
        const dx = v.x - u.x;
        const dy = v.y - u.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const targetDist = e.type === 'CONTAINS' ? 45 : 70;
        const force = (dist - targetDist) * kSpring;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        u.vx += fx;
        u.vy += fy;
        v.vx -= fx;
        v.vy -= fy;
    }

    // Apply velocities (pin repository node at 0, 0)
    for (const n of graphNodes) {
        if (n.type === 'repository') {
            n.vx = 0;
            n.vy = 0;
            n.x = 0;
            n.y = 0;
            continue;
        }
        n.x += n.vx;
        n.y += n.vy;
        n.vx *= damping;
        n.vy *= damping;
    }
}

/**
 * Main Canvas Render Function.
 */
function renderCanvasGraph() {
    const canvas = document.getElementById('graph-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    ctx.save();
    // Apply camera pan & zoom
    ctx.translate(graphCamera.x, graphCamera.y);
    ctx.scale(graphCamera.scale, graphCamera.scale);

    // Draw subtle grid
    drawGraphGrid(ctx, canvas);

    // 1. Draw Edges
    for (const edge of graphEdges) {
        const u = edge.sourceNode;
        const v = edge.targetNode;

        const isFiltered = (activeGraphFilter !== 'all') &&
                           (u.type !== activeGraphFilter && v.type !== activeGraphFilter);

        ctx.strokeStyle = edge.color;
        ctx.lineWidth = (edge === selectedGraphNode || u === selectedGraphNode || v === selectedGraphNode) ? 2.5 : 1;
        ctx.globalAlpha = isFiltered ? 0.08 : ((u === selectedGraphNode || v === selectedGraphNode) ? 0.9 : 0.4);

        if (edge.type === 'INHERITS' || edge.type === 'DEPENDS_ON') {
            ctx.setLineDash([4, 4]);
        } else {
            ctx.setLineDash([]);
        }

        ctx.beginPath();
        ctx.moveTo(u.x, u.y);
        ctx.lineTo(v.x, v.y);
        ctx.stroke();

        // Draw small directional arrow at target
        drawEdgeArrow(ctx, u.x, u.y, v.x, v.y, v.radius);
    }

    ctx.setLineDash([]);

    // 2. Draw Nodes
    for (const node of graphNodes) {
        const isMatched = (activeGraphFilter === 'all') || (node.type === activeGraphFilter);
        const isSelected = (node === selectedGraphNode);
        const isHovered = (node === hoveredGraphNode);

        ctx.globalAlpha = isMatched ? 1.0 : 0.15;

        // Outer halo / glow for selected or hovered
        if (isSelected || isHovered) {
            ctx.beginPath();
            ctx.arc(node.x, node.y, node.radius + 5, 0, Math.PI * 2);
            ctx.fillStyle = isSelected ? 'rgba(59, 130, 246, 0.4)' : 'rgba(255, 255, 255, 0.25)';
            ctx.fill();
        }

        // Main node circle
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
        ctx.fillStyle = node.color;
        ctx.fill();
        ctx.strokeStyle = isSelected ? '#ffffff' : 'rgba(15, 23, 42, 0.8)';
        ctx.lineWidth = isSelected ? 2.5 : 1.5;
        ctx.stroke();

        // Node Label (for prominent nodes or hovered/selected nodes)
        const showLabel = isSelected || isHovered || node.type === 'repository' ||
                          node.type === 'class' || (node.type === 'file' && graphCamera.scale > 0.85);

        if (showLabel && isMatched) {
            ctx.font = `${node.type === 'repository' ? 'bold 12px' : '10px'} Inter, sans-serif`;
            ctx.fillStyle = '#f8fafc';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';
            ctx.fillText(node.label || node.name, node.x, node.y + node.radius + 3);
        }
    }

    ctx.restore();
}

/**
 * Draw directional arrow on edge.
 */
function drawEdgeArrow(ctx, x1, y1, x2, y2, targetRadius) {
    const angle = Math.atan2(y2 - y1, x2 - x1);
    const arrowLen = 6;
    const arrowX = x2 - Math.cos(angle) * (targetRadius + 2);
    const arrowY = y2 - Math.sin(angle) * (targetRadius + 2);

    ctx.beginPath();
    ctx.moveTo(arrowX, arrowY);
    ctx.lineTo(
        arrowX - arrowLen * Math.cos(angle - Math.PI / 6),
        arrowY - arrowLen * Math.sin(angle - Math.PI / 6)
    );
    ctx.lineTo(
        arrowX - arrowLen * Math.cos(angle + Math.PI / 6),
        arrowY - arrowLen * Math.sin(angle + Math.PI / 6)
    );
    ctx.closePath();
    ctx.fillStyle = ctx.strokeStyle;
    ctx.fill();
}

/**
 * Draw background coordinate grid.
 */
function drawGraphGrid(ctx, canvas) {
    const gridSize = 40;
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.03)';
    ctx.lineWidth = 1;

    const left = -graphCamera.x / graphCamera.scale;
    const top = -graphCamera.y / graphCamera.scale;
    const right = (canvas.width - graphCamera.x) / graphCamera.scale;
    const bottom = (canvas.height - graphCamera.y) / graphCamera.scale;

    const startX = Math.floor(left / gridSize) * gridSize;
    const startY = Math.floor(top / gridSize) * gridSize;

    ctx.beginPath();
    for (let x = startX; x < right; x += gridSize) {
        ctx.moveTo(x, top);
        ctx.lineTo(x, bottom);
    }
    for (let y = startY; y < bottom; y += gridSize) {
        ctx.moveTo(left, y);
        ctx.lineTo(right, y);
    }
    ctx.stroke();
}

/**
 * Setup Canvas Event Handlers (Pan, Zoom, Hover, Click).
 * @param {HTMLCanvasElement} canvas
 */
function setupCanvasInteractions(canvas) {
    if (canvas._hasInteractions) return;
    canvas._hasInteractions = true;

    // 1. Mouse Down (Start Pan)
    canvas.addEventListener('mousedown', (e) => {
        isGraphDragging = true;
        graphDragStart = { x: e.clientX, y: e.clientY };
    });

    // 2. Mouse Move (Pan & Hover Hit Test)
    window.addEventListener('mousemove', (e) => {
        if (isGraphDragging) {
            const dx = e.clientX - graphDragStart.x;
            const dy = e.clientY - graphDragStart.y;
            graphCamera.x += dx;
            graphCamera.y += dy;
            graphDragStart = { x: e.clientX, y: e.clientY };
            renderCanvasGraph();
        } else {
            // Check hit test over nodes
            const rect = canvas.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;

            if (mouseX >= 0 && mouseX <= canvas.width && mouseY >= 0 && mouseY <= canvas.height) {
                const worldX = (mouseX - graphCamera.x) / graphCamera.scale;
                const worldY = (mouseY - graphCamera.y) / graphCamera.scale;

                let hit = null;
                for (let i = graphNodes.length - 1; i >= 0; i--) {
                    const n = graphNodes[i];
                    const d = Math.sqrt((worldX - n.x) ** 2 + (worldY - n.y) ** 2);
                    if (d <= n.radius + 3) {
                        hit = n;
                        break;
                    }
                }

                if (hit !== hoveredGraphNode) {
                    hoveredGraphNode = hit;
                    canvas.style.cursor = hit ? 'pointer' : 'grab';
                    renderCanvasGraph();
                }
            }
        }
    });

    // 3. Mouse Up (End Pan)
    window.addEventListener('mouseup', () => {
        isGraphDragging = false;
    });

    // 4. Click (Select Node)
    canvas.addEventListener('click', (e) => {
        const rect = canvas.getBoundingClientRect();
        const worldX = (e.clientX - rect.left - graphCamera.x) / graphCamera.scale;
        const worldY = (e.clientY - rect.top - graphCamera.y) / graphCamera.scale;

        let clicked = null;
        for (let i = graphNodes.length - 1; i >= 0; i--) {
            const n = graphNodes[i];
            const d = Math.sqrt((worldX - n.x) ** 2 + (worldY - n.y) ** 2);
            if (d <= n.radius + 4) {
                clicked = n;
                break;
            }
        }

        selectedGraphNode = clicked;
        inspectGraphNode(clicked);
        renderCanvasGraph();
    });

    // 5. Wheel (Smooth Zoom)
    canvas.addEventListener('wheel', (e) => {
        e.preventDefault();
        const rect = canvas.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;

        const zoomFactor = e.deltaY < 0 ? 1.15 : 0.87;
        const newScale = Math.min(Math.max(graphCamera.scale * zoomFactor, 0.2), 4.0);

        // Zoom relative to cursor point
        graphCamera.x = mouseX - (mouseX - graphCamera.x) * (newScale / graphCamera.scale);
        graphCamera.y = mouseY - (mouseY - graphCamera.y) * (newScale / graphCamera.scale);
        graphCamera.scale = newScale;

        renderCanvasGraph();
    }, { passive: false });
}

/**
 * Filter graph nodes by entity type.
 * @param {string} type
 * @param {HTMLElement} btnEl
 */
function filterGraphNodes(type, btnEl) {
    activeGraphFilter = type;
    document.querySelectorAll('.graph-filter-btn').forEach(btn => btn.classList.remove('active'));
    if (btnEl) btnEl.classList.add('active');
    renderCanvasGraph();
}

/**
 * Reset graph view camera to center.
 */
function resetGraphView() {
    const canvas = document.getElementById('graph-canvas');
    if (!canvas) return;

    graphCamera = {
        x: canvas.width / 2,
        y: canvas.height / 2,
        scale: 0.85,
    };
    selectedGraphNode = null;
    inspectGraphNode(null);
    renderCanvasGraph();
}

/**
 * Display Node details in the Node Inspector panel.
 * @param {object|null} node
 */
function inspectGraphNode(node) {
    const typeBadge = document.getElementById('inspector-node-type');
    const bodyEl = document.getElementById('inspector-body');
    if (!bodyEl) return;

    if (!node) {
        if (typeBadge) {
            typeBadge.textContent = 'Select Node';
            typeBadge.className = 'badge badge-secondary';
        }
        bodyEl.innerHTML = '<p class="inspector-placeholder">Click any node in the graph to inspect its properties, parent hierarchy, and connected relationships.</p>';
        return;
    }

    if (typeBadge) {
        typeBadge.textContent = node.type.toUpperCase();
        typeBadge.className = 'badge badge-primary';
    }

    // Find incoming and outgoing edges
    const incoming = graphEdges.filter(e => e.target === node.id);
    const outgoing = graphEdges.filter(e => e.source === node.id);

    bodyEl.innerHTML = `
        <div class="inspector-row">
            <div class="inspector-row-label">Node Identifier</div>
            <div class="inspector-row-value"><span class="inspector-code-val">${escapeHtml(node.id)}</span></div>
        </div>

        <div class="inspector-row">
            <div class="inspector-row-label">Name / Label</div>
            <div class="inspector-row-value"><strong>${escapeHtml(node.label || node.name)}</strong></div>
        </div>

        ${node.file || node.path ? `
            <div class="inspector-row">
                <div class="inspector-row-label">Location / Path</div>
                <div class="inspector-row-value">${escapeHtml(node.file || node.path)}${node.line_start ? `:${node.line_start}` : ''}</div>
            </div>
        ` : ''}

        ${node.language ? `
            <div class="inspector-row">
                <div class="inspector-row-label">Language</div>
                <div class="inspector-row-value"><span class="badge badge-info">${escapeHtml(node.language)}</span></div>
            </div>
        ` : ''}

        ${node.parameters && node.parameters.length > 0 ? `
            <div class="inspector-row">
                <div class="inspector-row-label">Parameters</div>
                <div class="inspector-row-value">
                    ${node.parameters.map(p => `<span class="ast-pill ast-pill-arg">${escapeHtml(p)}</span>`).join(' ')}
                </div>
            </div>
        ` : ''}

        ${node.docstring ? `
            <div class="inspector-row">
                <div class="inspector-row-label">Documentation</div>
                <div class="ast-card-doc" style="max-height: 80px; overflow-y: auto;">"${escapeHtml(node.docstring)}"</div>
            </div>
        ` : ''}

        <div class="inspector-row" style="margin-top: 1rem;">
            <div class="inspector-row-label">Incoming Relations (${incoming.length})</div>
            <div class="inspector-row-value">
                ${incoming.length > 0 ? incoming.slice(0, 10).map(e => `
                    <div class="inspector-edge-chip">
                        <span class="legend-color-dot" style="background:${e.color}"></span>
                        <span>${escapeHtml(e.sourceNode ? e.sourceNode.name : e.source)}</span>
                        <span class="text-muted">(${escapeHtml(e.type)})</span>
                    </div>
                `).join('') : '<span class="text-muted">None (Root or External)</span>'}
            </div>
        </div>

        <div class="inspector-row" style="margin-top: 0.75rem;">
            <div class="inspector-row-label">Outgoing Relations (${outgoing.length})</div>
            <div class="inspector-row-value">
                ${outgoing.length > 0 ? outgoing.slice(0, 15).map(e => `
                    <div class="inspector-edge-chip">
                        <span class="legend-color-dot" style="background:${e.color}"></span>
                        <span>${escapeHtml(e.type)}</span> →
                        <span>${escapeHtml(e.targetNode ? e.targetNode.name : e.target)}</span>
                    </div>
                `).join('') : '<span class="text-muted">Leaf Node</span>'}
            </div>
        </div>
    `;
}
// ==============================================================================
// Phase 8: Whole Repository Architecture Explorer Controller
// ==============================================================================

let currentArchData = null;
let currentArchRepo = null;
let currentSelectedCompIndex = 0;

const ARCH_CATEGORY_BADGE_MAP = {
    'Source Code': 'badge-primary',
    'Core Application': 'badge-primary',
    'Core Modules': 'badge-primary',
    'Core Module': 'badge-primary',
    'API Modules': 'badge-info',
    'API & Routes': 'badge-info',
    'Tests': 'badge-secondary',
    'Tests & Verification': 'badge-secondary',
    'Documentation': 'badge-secondary',
    'Assets & Media': 'badge-secondary',
    'Configuration': 'badge-warning',
    'Utilities': 'badge-info',
    'Scripts': 'badge-secondary',
    'Examples': 'badge-secondary',
    'Root Modules': 'badge-primary'
};

/**
 * Initialize Clean Human-Readable Architecture Explorer on the /architecture route.
 */
async function initArchitecturePage() {
    const wrapper = document.querySelector('.arch-clean-wrapper');
    if (!wrapper) return; // Not on the architecture page

    // Parse URL params for repo
    const urlParams = new URLSearchParams(window.location.search);
    const repoParam = urlParams.get('repo');

    // Populate repository dropdown and retrieve cached repos
    const cachedRepos = await populateArchRepoSelector();

    let targetRepo = repoParam;
    if (!targetRepo) {
        try {
            targetRepo = localStorage.getItem('codelens_last_repo');
        } catch (e) {}
    }

    if (!targetRepo && typeof currentAnalysisData !== 'undefined' && currentAnalysisData && currentAnalysisData.repository) {
        targetRepo = currentAnalysisData.repository.full_name;
    }

    if (!targetRepo && cachedRepos && cachedRepos.length > 0) {
        targetRepo = cachedRepos[0];
    }

    if (!targetRepo) {
        targetRepo = 'psf/requests';
    }

    if (targetRepo) {
        const emptyEl = document.getElementById('arch-empty-state');
        if (emptyEl) emptyEl.style.display = 'none';
        loadArchitectureData(targetRepo);
    } else {
        const emptyEl = document.getElementById('arch-empty-state');
        if (emptyEl) emptyEl.style.display = 'block';
        const loadingEl = document.getElementById('arch-clean-loading');
        if (loadingEl) loadingEl.style.display = 'none';
        const panels = document.querySelectorAll('.arch-tab-panel');
        panels.forEach(p => p.style.display = 'none');
    }
}

/**
 * Populate repository select dropdown with cached and sample repositories.
 * Returns array of available cached repository full names.
 */
async function populateArchRepoSelector() {
    const select = document.getElementById('arch-repo-select');
    if (!select) return [];

    try {
        const [archRes, repRes] = await Promise.all([
            fetch('/api/repositories/analysis/cached').then(r => r.json()).catch(() => ({})),
            fetch('/api/repositories/report/cached').then(r => r.json()).catch(() => ({}))
        ]);

        const reposSet = new Set();
        const availableRepos = [];
        (archRes.repositories || []).forEach(r => {
            const name = r.full_name || (r.owner && r.name ? `${r.owner}/${r.name}` : null);
            if (name) {
                reposSet.add(name);
                availableRepos.push(name);
            }
        });
        (repRes.reports || []).forEach(r => {
            if (r.full_name) {
                reposSet.add(r.full_name);
                if (!availableRepos.includes(r.full_name)) availableRepos.push(r.full_name);
            }
        });

        // Ensure key sample candidate repos are in list
        ['psf/requests', 'bottlepy/bottle', 'pallets/flask', 'fastapi/fastapi'].forEach(r => reposSet.add(r));

        select.innerHTML = '<option value="">-- Choose Analyzed Repository --</option>';
        Array.from(reposSet).sort().forEach(r => {
            const opt = document.createElement('option');
            opt.value = r;
            opt.textContent = r;
            select.appendChild(opt);
        });

        if (currentArchRepo) {
            select.value = currentArchRepo;
        }
        return availableRepos;
    } catch (err) {
        console.error('Error populating architecture repo dropdown:', err);
        return [];
    }
}

/**
 * Handle repository selection change from dropdown.
 * @param {string} repoName
 */
function onArchRepoSelected(repoName) {
    if (!repoName) return;
    loadArchitectureData(repoName);
}

/**
 * Fetch and populate architecture data for a repository.
 * @param {string} repoInput
 * @param {boolean} forceRefresh
 */
async function loadArchitectureData(repoInput, forceRefresh = false) {
    if (!repoInput) return;
    currentArchRepo = repoInput.trim();

    try {
        localStorage.setItem('codelens_last_repo', currentArchRepo);
    } catch (e) {}
    syncNavigationRepoParams(currentArchRepo);

    const select = document.getElementById('arch-repo-select');
    if (select) select.value = currentArchRepo;

    const emptyEl = document.getElementById('arch-empty-state');
    if (emptyEl) emptyEl.style.display = 'none';

    const loadingEl = document.getElementById('arch-clean-loading');
    if (loadingEl) loadingEl.style.display = 'block';

    try {
        const response = await fetch('/api/repositories/architecture', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                repo: currentArchRepo,
                force_refresh: forceRefresh
            })
        });

        const res = await response.json();
        if (!response.ok || !res.success) {
            throw new Error(res.error || 'Failed to fetch architecture data.');
        }

        currentArchData = res.data || res;

        // 1. Update Header details
        updateCleanArchHeader(currentArchData);

        // 2. Render all 4 Navigation Tabs
        renderCleanArchitectureOverview(currentArchData);
        renderCleanComponentsTab(currentArchData);
        renderCleanDependenciesTab(currentArchData);
        renderCleanCodeExplorerTab(currentArchData);

        // Update URL query param smoothly
        const newUrl = `${window.location.pathname}?repo=${encodeURIComponent(currentArchData.repository.full_name)}`;
        window.history.pushState({ path: newUrl }, '', newUrl);

        showToast('Architecture Loaded', `Loaded architecture model for ${currentArchData.repository.full_name}`, 'success');

    } catch (err) {
        console.error('[CodeLens AI] Architecture loading error:', err);
        showToast('Architecture Notice', 'Unable to load architecture. Please try again.', 'error');
    } finally {
        if (loadingEl) loadingEl.style.display = 'none';
    }
}

/**
 * Update top header card and external navigation links.
 * @param {object} data
 */
function updateCleanArchHeader(data) {
    if (!data) return;
    const repo = data.repository || {};
    const stats = data.statistics || {};

    const titleEl = document.getElementById('arch-repo-title');
    const descEl = document.getElementById('arch-repo-desc');
    const langEl = document.getElementById('arch-repo-lang');
    const dagEl = document.getElementById('arch-repo-dag');

    if (titleEl) titleEl.textContent = repo.full_name || repo.name || 'Repository Architecture';
    if (descEl) descEl.textContent = repo.description || 'Deterministic high-level architecture synthesized from directory structure, AST symbols, and dependency relationships.';
    if (langEl) langEl.textContent = repo.primary_language || 'Codebase';

    if (dagEl) {
        if (stats.cycles_count > 0) {
            dagEl.textContent = `Cycles: ${stats.cycles_count} detected`;
            dagEl.className = 'badge badge-warning';
        } else {
            dagEl.textContent = 'No detected cycles';
            dagEl.className = 'badge badge-success';
        }
    }

    // Secondary action links & Cross-Feature CTA
    const btnAnalysis = document.getElementById('btn-detailed-analysis');
    const btnGraph = document.getElementById('btn-semantic-graph');
    const btnReport = document.getElementById('btn-project-report');
    const btnChat = document.getElementById('btn-chat-assistant');
    const btnArchChatCta = document.getElementById('btn-arch-chat-cta');

    if (repo.full_name) {
        const repoParam = encodeURIComponent(repo.full_name);
        if (btnAnalysis) btnAnalysis.href = `/analysis?repo=${repoParam}`;
        if (btnGraph) btnGraph.href = `/graph?repo=${repoParam}`;
        if (btnReport) btnReport.href = `/report?repo=${repoParam}`;
        if (btnChat) btnChat.href = `/chat?repo=${repoParam}`;
        if (btnArchChatCta) btnArchChatCta.href = `/chat?repo=${repoParam}`;
        syncNavigationRepoParams(repo.full_name);
    }
}

/**
 * Switch active navigation tab between Overview, Components, Dependencies, and Code Explorer.
 * @param {string} tabName
 * @param {HTMLElement} [btnEl]
 */
function switchArchTab(tabName, btnEl) {
    document.querySelectorAll('.arch-nav-tab-btn').forEach(b => b.classList.remove('active'));
    if (btnEl) {
        btnEl.classList.add('active');
    } else {
        const matchingBtn = document.querySelector(`.arch-nav-tab-btn[data-tab="${tabName}"]`);
        if (matchingBtn) matchingBtn.classList.add('active');
    }

    document.querySelectorAll('.arch-tab-panel').forEach(panel => {
        panel.style.display = 'none';
        panel.classList.remove('active');
    });

    const activePanel = document.getElementById(`tab-${tabName}`);
    if (activePanel) {
        activePanel.style.display = 'block';
        activePanel.classList.add('active');
    }
}

/**
 * TAB 1: Render clean hierarchical tree architecture (Root -> Branch -> 5-10 Component Cards).
 * @param {object} data
 */
function renderCleanArchitectureOverview(data) {
    if (!data) return;
    const repo = data.repository || {};
    const stats = data.statistics || {};
    const subsystems = data.major_subsystems || (data.levels && data.levels.major_subsystems) || [];

    // 1. Root Repository Card
    const rootName = document.getElementById('diag-root-name');
    const rootLang = document.getElementById('diag-root-lang');
    const rootSubs = document.getElementById('diag-root-subs-count');
    const rootDag = document.getElementById('diag-root-dag-status');

    if (rootName) rootName.textContent = repo.full_name || repo.name || 'Repository Root';
    if (rootLang) rootLang.textContent = repo.primary_language || 'Codebase';
    if (rootSubs) rootSubs.textContent = `${subsystems.length} Major Components`;
    if (rootDag) rootDag.textContent = stats.cycles_count > 0 ? `${stats.cycles_count} Cycles Detected` : 'Acyclic Directed Flow';

    // 2. Render Subsystems Grid
    const grid = document.getElementById('diag-components-grid');
    if (grid) {
        if (subsystems.length === 0) {
            grid.innerHTML = '<p class="text-muted" style="text-align: center; grid-column: 1 / -1; padding: 2rem;">No distinct subsystems discovered in analysis.</p>';
        } else {
            grid.innerHTML = subsystems.map((sub, idx) => {
                const badgeClass = ARCH_CATEGORY_BADGE_MAP[sub.category] || 'badge-secondary';
                const keyFiles = sub.key_files || [];
                return `
                    <div class="arch-comp-card ${idx === 0 ? 'selected-comp-card' : ''}" id="arch-comp-card-${idx}" onclick="selectArchitectureComponent(${idx})">
                        <div class="arch-comp-top">
                            <div class="arch-comp-title-wrap">
                                <span class="arch-comp-icon">${sub.icon || '📦'}</span>
                                <span class="arch-comp-name" title="${escapeHtml(sub.name)}">${escapeHtml(sub.short_name || sub.name)}</span>
                            </div>
                            <span class="badge ${badgeClass}" style="font-size: 0.68rem;">${escapeHtml(sub.category || 'Component')}</span>
                        </div>
                        <p class="arch-comp-desc">${escapeHtml(sub.description || 'System component responsibility.')}</p>
                        <div class="arch-comp-metrics">
                            <span>📄 <strong>${sub.files_count || 0}</strong> files</span>
                            <span>🅲 <strong>${sub.classes_count || 0}</strong> classes</span>
                            <span>🅵 <strong>${sub.functions_count || 0}</strong> routines</span>
                        </div>
                        <div>
                            <div class="arch-comp-key-title">Key Files:</div>
                            <div class="arch-comp-key-files">
                                ${keyFiles.length === 0 ? '<span class="text-muted" style="font-size:0.75rem;">None</span>' : keyFiles.slice(0, 3).map(kf => `
                                    <div class="arch-comp-file-chip" onclick="drillToFileInExplorer('${escapeHtml(kf.path)}', event)" title="${escapeHtml(kf.role || kf.path)}">
                                        <span class="arch-comp-chip-name">📄 ${escapeHtml(kf.name)}</span>
                                        <span class="arch-comp-chip-meta">${kf.classes_count || 0}c / ${kf.functions_count || 0}f</span>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }
    }

    // Select first subsystem by default
    if (subsystems.length > 0) {
        selectArchitectureComponent(0);
    }
}

/**
 * Update Selected Component Detail Panel with rich structural and AST data.
 * @param {number} index
 */
function selectArchitectureComponent(index) {
    if (!currentArchData) return;
    const subsystems = currentArchData.major_subsystems || (currentArchData.levels && currentArchData.levels.major_subsystems) || [];
    if (!subsystems.length || index < 0 || index >= subsystems.length) return;

    currentSelectedCompIndex = index;

    // Highlight card visually
    document.querySelectorAll('.arch-comp-card').forEach((c, i) => {
        c.classList.toggle('selected-comp-card', i === index);
    });

    const sub = subsystems[index];

    const iconEl = document.getElementById('sel-comp-icon');
    const titleEl = document.getElementById('sel-comp-title');
    const catEl = document.getElementById('sel-comp-category');
    const purposeEl = document.getElementById('sel-comp-purpose');
    const modulesEl = document.getElementById('sel-comp-modules');
    const filesEl = document.getElementById('sel-comp-files');
    const classesEl = document.getElementById('sel-comp-classes');
    const funcsEl = document.getElementById('sel-comp-functions');
    const depsEl = document.getElementById('sel-comp-dependencies');
    const relsEl = document.getElementById('sel-comp-relationships');

    if (iconEl) iconEl.textContent = sub.icon || '📦';
    if (titleEl) titleEl.textContent = sub.name;
    if (catEl) {
        catEl.textContent = sub.category || 'Component';
        catEl.className = `badge ${ARCH_CATEGORY_BADGE_MAP[sub.category] || 'badge-secondary'}`;
    }
    if (purposeEl) {
        purposeEl.textContent = sub.description || 'Core component of the architecture model.';
    }

    // Important Modules / Folders
    if (modulesEl) {
        const submods = sub.submodules || [];
        if (submods.length === 0) {
            modulesEl.textContent = sub.path || '(root)';
        } else {
            modulesEl.innerHTML = submods.map(m => `<div>📁 ${escapeHtml(m)}</div>`).join('');
        }
    }

    // Important Files
    if (filesEl) {
        const keyFiles = sub.key_files || [];
        if (keyFiles.length === 0) {
            filesEl.innerHTML = '<p class="text-muted" style="font-size:0.8rem; margin:0;">No key files identified.</p>';
        } else {
            filesEl.innerHTML = keyFiles.map(kf => `
                <div class="arch-detail-file-row" onclick="drillToFileInExplorer('${escapeHtml(kf.path)}')">
                    <div>
                        <div class="arch-detail-file-name">📄 ${escapeHtml(kf.name)}</div>
                        <div class="arch-detail-file-sub">${escapeHtml(kf.role || kf.path)}</div>
                    </div>
                    <span class="badge badge-secondary" style="font-size:0.68rem;">${kf.classes_count || 0} classes / ${kf.functions_count || 0} routines</span>
                </div>
            `).join('');
        }
    }

    // Key Classes
    if (classesEl) {
        const classes = sub.classes || [];
        if (classes.length === 0) {
            classesEl.innerHTML = '<span class="text-muted">None declared in this component.</span>';
        } else {
            classesEl.innerHTML = classes.map(c => {
                const name = typeof c === 'string' ? c : c.name;
                const bases = c.bases && c.bases.length ? ` : ${c.bases.join(', ')}` : '';
                return `<div>🅲 <strong>${escapeHtml(name)}</strong><span style="color:var(--text-muted); font-size:0.75rem;">${escapeHtml(bases)}</span></div>`;
            }).join('');
        }
    }

    // Key Functions & Routines
    if (funcsEl) {
        const funcs = sub.functions || [];
        if (funcs.length === 0) {
            funcsEl.innerHTML = '<span class="text-muted">None declared in this component.</span>';
        } else {
            funcsEl.innerHTML = funcs.map(f => {
                const name = typeof f === 'string' ? f : f.name;
                const args = f.args && f.args.length ? `(${f.args.join(', ')})` : '()';
                return `<div>🅵 <strong>${escapeHtml(name)}</strong><span style="color:var(--text-muted); font-size:0.75rem;">${escapeHtml(args)}</span></div>`;
            }).join('');
        }
    }

    // Packages & Dependencies
    if (depsEl) {
        const deps = sub.dependencies || [];
        if (deps.length === 0) {
            depsEl.innerHTML = '<span class="text-muted" style="font-size:0.8rem;">No external dependencies imported directly.</span>';
        } else {
            depsEl.innerHTML = deps.map(d => `<span class="badge badge-secondary" style="font-size:0.72rem;">${escapeHtml(d)}</span>`).join('');
        }
    }

    // Component Relationships & Flow
    if (relsEl) {
        const inFlows = sub.inbound_flows || [];
        const outFlows = sub.outbound_flows || [];

        if (inFlows.length === 0 && outFlows.length === 0) {
            relsEl.innerHTML = '<div class="text-muted">Self-contained subsystem with minimal direct coupling to other top-level components.</div>';
        } else {
            let relHtml = '';
            if (outFlows.length > 0) {
                relHtml += '<div style="margin-bottom:0.5rem;"><strong style="color:var(--text-primary); font-size:0.75rem; text-transform:uppercase;">Calls / Imports:</strong>';
                outFlows.forEach(f => {
                    relHtml += `<div style="margin-top:0.25rem;">&bull; &rarr; <strong>${escapeHtml(f.target)}</strong> <span style="color:var(--text-muted);">(${f.relationship_count} connection${f.relationship_count > 1 ? 's' : ''})</span></div>`;
                });
                relHtml += '</div>';
            }
            if (inFlows.length > 0) {
                relHtml += '<div><strong style="color:var(--text-primary); font-size:0.75rem; text-transform:uppercase;">Imported / Called By:</strong>';
                inFlows.forEach(f => {
                    relHtml += `<div style="margin-top:0.25rem;">&bull; &larr; <strong>${escapeHtml(f.source)}</strong> <span style="color:var(--text-muted);">(${f.relationship_count} connection${f.relationship_count > 1 ? 's' : ''})</span></div>`;
                });
                relHtml += '</div>';
            }
            relsEl.innerHTML = relHtml;
        }
    }
}

/**
 * Drill currently selected component into the Code Explorer tab.
 */
function drillCurrentComponentToExplorer() {
    if (!currentArchData) return;
    const subsystems = currentArchData.major_subsystems || (currentArchData.levels && currentArchData.levels.major_subsystems) || [];
    const sub = subsystems[currentSelectedCompIndex] || subsystems[0];
    if (!sub) return;

    switchArchTab('explorer', document.querySelector('.arch-nav-tab-btn[data-tab="explorer"]'));
    const compSelect = document.getElementById('explorer-component-select');
    if (compSelect) {
        compSelect.value = String(currentSelectedCompIndex);
        onExplorerComponentChange(String(currentSelectedCompIndex));
    }
}

/**
 * TAB 2: Render Complete Structured Grid of All 5-10 Components.
 * @param {object} data
 */
function renderCleanComponentsTab(data) {
    const grid = document.getElementById('all-components-grid');
    if (!grid) return;

    const subsystems = data.major_subsystems || (data.levels && data.levels.major_subsystems) || [];
    if (subsystems.length === 0) {
        grid.innerHTML = '<p class="text-muted" style="grid-column: 1 / -1; text-align: center; padding: 2rem;">No major components found.</p>';
        return;
    }

    grid.innerHTML = subsystems.map((sub, idx) => {
        const badgeClass = ARCH_CATEGORY_BADGE_MAP[sub.category] || 'badge-secondary';
        const keyFiles = sub.key_files || [];
        const classes = sub.classes || [];

        return `
            <div class="card" style="padding: 1.5rem; display: flex; flex-direction: column; justify-content: space-between;">
                <div>
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.75rem; gap: 0.5rem;">
                        <div style="display: flex; align-items: center; gap: 0.5rem;">
                            <span style="font-size: 1.4rem;">${sub.icon || '📦'}</span>
                            <h4 style="margin: 0; font-size: 1.1rem; color: var(--text-primary); font-weight: 700;">${escapeHtml(sub.name)}</h4>
                        </div>
                        <span class="badge ${badgeClass}" style="font-size: 0.72rem; white-space: nowrap;">${escapeHtml(sub.category || 'Component')}</span>
                    </div>

                    <p style="font-size: 0.85rem; color: var(--text-secondary); margin: 0 0 1rem 0; line-height: 1.5;">
                        ${escapeHtml(sub.description || 'System architectural component.')}
                    </p>

                    <div style="display: flex; gap: 0.75rem; font-size: 0.8rem; color: var(--text-muted); margin-bottom: 1rem; padding-bottom: 0.75rem; border-bottom: 1px solid var(--border-color);">
                        <span>📄 <strong>${sub.files_count || 0}</strong> files</span>
                        <span>🅲 <strong>${sub.classes_count || 0}</strong> classes</span>
                        <span>🅵 <strong>${sub.functions_count || 0}</strong> routines</span>
                    </div>

                    <div style="margin-bottom: 1rem;">
                        <div style="font-size: 0.75rem; font-weight: 700; text-transform: uppercase; color: var(--text-muted); margin-bottom: 0.4rem;">
                            Key Files (${keyFiles.length}):
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 0.35rem;">
                            ${keyFiles.length === 0 ? '<span class="text-muted" style="font-size:0.75rem;">None</span>' : keyFiles.slice(0, 4).map(kf => `
                                <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.35rem 0.5rem; background: var(--bg-surface-secondary); border-radius: 4px; font-size: 0.78rem; font-family: var(--font-mono); cursor: pointer;"
                                     onclick="drillToFileInExplorer('${escapeHtml(kf.path)}')" title="${escapeHtml(kf.role || kf.path)}">
                                    <span style="color: var(--primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 220px;">📄 ${escapeHtml(kf.name)}</span>
                                    <span style="font-size: 0.7rem; color: var(--text-muted);">${kf.classes_count || 0}c / ${kf.functions_count || 0}f</span>
                                </div>
                            `).join('')}
                        </div>
                    </div>

                    ${classes.length > 0 ? `
                        <div style="margin-bottom: 1rem;">
                            <div style="font-size: 0.75rem; font-weight: 700; text-transform: uppercase; color: #7c3aed; margin-bottom: 0.35rem;">
                                Key Classes:
                            </div>
                            <div style="font-size: 0.78rem; font-family: var(--font-mono); color: #7c3aed; display: flex; flex-wrap: wrap; gap: 0.35rem;">
                                ${classes.slice(0, 4).map(c => `<span>🅲 ${escapeHtml(typeof c === 'string' ? c : c.name)}</span>`).join(', ')}
                            </div>
                        </div>
                    ` : ''}
                </div>

                <div style="padding-top: 1rem; border-top: 1px solid var(--border-color); display: flex; gap: 0.5rem;">
                    <button class="btn btn-xs btn-outline" style="flex: 1;" onclick="inspectComponentFromGrid(${idx})">
                        View in Overview
                    </button>
                    <button class="btn btn-xs btn-primary" style="flex: 1;" onclick="drillSubsystemToExplorer(${idx})">
                        Code Explorer &rarr;
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

function inspectComponentFromGrid(index) {
    switchArchTab('overview', document.querySelector('.arch-nav-tab-btn[data-tab="overview"]'));
    selectArchitectureComponent(index);
    const cardEl = document.getElementById(`arch-comp-card-${index}`);
    if (cardEl) {
        cardEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
}

function drillSubsystemToExplorer(index) {
    currentSelectedCompIndex = index;
    drillCurrentComponentToExplorer();
}

/**
 * TAB 3: Render High-Level Dependencies (Component Interaction Paths & External Packages).
 * @param {object} data
 */
function renderCleanDependenciesTab(data) {
    const flowsContainer = document.getElementById('arch-flows-container');
    const extContainer = document.getElementById('arch-external-packages-container');

    const flows = data.component_flows || (data.levels && data.levels.component_flows) || [];
    const depAnalysis = data.dependency_analysis || {};

    // 1. High-level flows
    if (flowsContainer) {
        if (flows.length === 0) {
            flowsContainer.innerHTML = `
                <div style="text-align: center; padding: 2rem 1rem; background: var(--bg-surface-secondary); border-radius: var(--radius-sm); border: 1px solid var(--border-color);">
                    <div style="font-size: 1.5rem; margin-bottom: 0.5rem; color: #10b981;">✓</div>
                    <div style="font-weight: 600; color: var(--text-primary); margin-bottom: 0.25rem;">Clean Modular Architecture</div>
                    <div style="font-size: 0.85rem; color: var(--text-muted);">Components are decoupled without cross-subsystem circular dependency chains.</div>
                </div>
            `;
        } else {
            flowsContainer.innerHTML = flows.map(f => `
                <div style="display: flex; align-items: center; justify-content: space-between; padding: 0.85rem 1.25rem; background: var(--bg-surface-secondary); border-radius: var(--radius-sm); border: 1px solid var(--border-color); flex-wrap: wrap; gap: 0.75rem;">
                    <div style="display: flex; align-items: center; gap: 0.75rem; font-size: 0.95rem;">
                        <span style="font-weight: 700; color: var(--text-primary);">${escapeHtml(f.source)}</span>
                        <span style="color: var(--primary); font-weight: 700; font-size: 1.1rem;">&rarr;</span>
                        <span style="font-weight: 700; color: var(--text-primary);">${escapeHtml(f.target)}</span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 0.75rem;">
                        <span style="font-size: 0.78rem; color: var(--text-muted); font-family: var(--font-mono);">${escapeHtml(f.sample_connection || '')}</span>
                        <span class="badge badge-primary" style="font-size: 0.72rem;">${f.relationship_count} connection${f.relationship_count > 1 ? 's' : ''}</span>
                    </div>
                </div>
            `).join('');
        }
    }

    // 2. External Packages
    if (extContainer) {
        const extPackages = depAnalysis.external_packages || [];
        const stdPackages = depAnalysis.standard_library_modules || [];
        const allPackages = extPackages.concat(stdPackages);

        if (allPackages.length === 0) {
            extContainer.innerHTML = '<p class="text-muted" style="grid-column: 1 / -1;">No external dependencies detected.</p>';
        } else {
            extContainer.innerHTML = allPackages.slice(0, 18).map(pkg => `
                <div style="padding: 0.75rem 1rem; background: var(--bg-surface-secondary); border-radius: var(--radius-sm); border: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <div style="font-weight: 600; font-family: var(--font-mono); font-size: 0.9rem; color: var(--text-primary);">${escapeHtml(pkg.name)}</div>
                        <div style="font-size: 0.72rem; color: var(--text-muted);">${pkg.type === 'standard_library' ? 'Standard Library' : 'Third-Party Dependency'}</div>
                    </div>
                    <span class="badge ${pkg.type === 'standard_library' ? 'badge-secondary' : 'badge-info'}" style="font-size: 0.7rem;">
                        ${pkg.occurrences || 1} imports
                    </span>
                </div>
            `).join('');
        }
    }
}

/**
 * TAB 4: Progressive 5-Level Code Explorer (Repo -> Component -> Folder -> File -> Class/Function).
 * @param {object} data
 */
function renderCleanCodeExplorerTab(data) {
    const compSelect = document.getElementById('explorer-component-select');
    if (!compSelect) return;

    const subsystems = data.major_subsystems || (data.levels && data.levels.major_subsystems) || [];
    compSelect.innerHTML = '<option value="">-- Choose Component --</option>';

    subsystems.forEach((sub, idx) => {
        const opt = document.createElement('option');
        opt.value = String(idx);
        opt.textContent = `${sub.icon || '📦'} ${sub.short_name || sub.name} (${sub.files_count || 0} files)`;
        compSelect.appendChild(opt);
    });

    if (subsystems.length > 0) {
        compSelect.value = "0";
        onExplorerComponentChange("0");
    }
}

function onExplorerComponentChange(subIndex) {
    const fileSelect = document.getElementById('explorer-file-select');
    const symbolsCard = document.getElementById('explorer-file-symbols-card');
    const placeholder = document.getElementById('explorer-empty-placeholder');

    if (!fileSelect || !currentArchData) return;

    if (!subIndex || subIndex === "") {
        fileSelect.innerHTML = '<option value="">-- Choose File --</option>';
        if (symbolsCard) symbolsCard.style.display = 'none';
        if (placeholder) placeholder.style.display = 'block';
        return;
    }

    const subsystems = currentArchData.major_subsystems || (currentArchData.levels && currentArchData.levels.major_subsystems) || [];
    const sub = subsystems[Number(subIndex)];
    if (!sub) return;

    // Filter files for this subsystem from level_3
    const allFiles = (currentArchData.levels && currentArchData.levels.level_3 && currentArchData.levels.level_3.files) || [];
    let compFiles = [];

    if (sub.path === '(root)') {
        compFiles = allFiles.filter(f => !f.path.includes('/'));
    } else {
        compFiles = allFiles.filter(f => f.path === sub.path || f.path.startsWith(sub.path + '/'));
    }

    if (compFiles.length === 0 && sub.key_files && sub.key_files.length) {
        compFiles = sub.key_files;
    }

    fileSelect.innerHTML = '<option value="">-- Choose File --</option>';
    compFiles.forEach(f => {
        const opt = document.createElement('option');
        opt.value = f.path;
        opt.textContent = `📄 ${f.name || f.path.split('/').pop()} (${f.classes_count || (f.classes ? f.classes.length : 0)}c / ${f.functions_count || (f.functions ? f.functions.length : 0)}f)`;
        fileSelect.appendChild(opt);
    });

    if (compFiles.length > 0) {
        fileSelect.value = compFiles[0].path;
        onExplorerFileChange(compFiles[0].path);
    } else {
        if (symbolsCard) symbolsCard.style.display = 'none';
        if (placeholder) placeholder.style.display = 'block';
    }
}

function onExplorerFileChange(filePath) {
    const symbolsCard = document.getElementById('explorer-file-symbols-card');
    const placeholder = document.getElementById('explorer-empty-placeholder');

    if (!filePath || !currentArchData) {
        if (symbolsCard) symbolsCard.style.display = 'none';
        if (placeholder) placeholder.style.display = 'block';
        return;
    }

    const allFiles = (currentArchData.levels && currentArchData.levels.level_3 && currentArchData.levels.level_3.files) || [];
    let file = allFiles.find(f => f.path === filePath || f.name === filePath);

    if (!file) {
        const subsystems = currentArchData.major_subsystems || (currentArchData.levels && currentArchData.levels.major_subsystems) || [];
        for (const sub of subsystems) {
            const kf = (sub.key_files || []).find(k => k.path === filePath || k.name === filePath);
            if (kf) {
                file = kf;
                break;
            }
        }
    }

    if (!file) {
        file = {
            name: filePath.split('/').pop(),
            path: filePath,
            language: 'Code',
            classes: [],
            functions: [],
            methods: [],
            imports: []
        };
    }

    if (symbolsCard) symbolsCard.style.display = 'block';
    if (placeholder) placeholder.style.display = 'none';

    // Populate File header
    const fnEl = document.getElementById('exp-sym-file-name');
    const fpEl = document.getElementById('exp-sym-file-path');
    const flEl = document.getElementById('exp-sym-lang');
    const fsEl = document.getElementById('exp-sym-size');

    if (fnEl) fnEl.textContent = file.name || filePath.split('/').pop();
    if (fpEl) fpEl.textContent = file.path || filePath;
    if (flEl) flEl.textContent = file.language || 'Python';
    if (fsEl) fsEl.textContent = file.size ? `${Number(file.size).toLocaleString()} B` : 'Tracked module';

    // 1. Classes
    const classes = file.classes || [];
    const clsCountEl = document.getElementById('exp-sym-classes-count');
    const clsListEl = document.getElementById('exp-sym-classes-list');
    if (clsCountEl) clsCountEl.textContent = classes.length;
    if (clsListEl) {
        if (classes.length === 0) {
            clsListEl.innerHTML = '<p class="text-muted" style="margin:0;">No classes declared in this file.</p>';
        } else {
            clsListEl.innerHTML = classes.map(c => {
                const name = typeof c === 'string' ? c : c.name;
                const bases = c.bases && c.bases.length ? ` : ${c.bases.join(', ')}` : '';
                const methodsCount = c.methods ? ` &bull; ${c.methods.length} methods` : '';
                return `
                    <div style="padding: 0.4rem 0; border-bottom: 1px solid var(--border-color);">
                        <div style="font-weight: 600; color: #7c3aed; font-family: var(--font-mono);">🅲 ${escapeHtml(name)}</div>
                        ${bases ? `<div style="font-size: 0.72rem; color: var(--text-muted); font-family: var(--font-mono);">${escapeHtml(bases)}</div>` : ''}
                        ${methodsCount ? `<div style="font-size: 0.7rem; color: var(--text-secondary);">${methodsCount}</div>` : ''}
                    </div>
                `;
            }).join('');
        }
    }

    // 2. Functions & Methods
    const routines = (file.functions || []).concat(file.methods || []);
    const fnCountEl = document.getElementById('exp-sym-routines-count');
    const fnListEl = document.getElementById('exp-sym-routines-list');
    if (fnCountEl) fnCountEl.textContent = routines.length;
    if (fnListEl) {
        if (routines.length === 0) {
            fnListEl.innerHTML = '<p class="text-muted" style="margin:0;">No routines declared in this file.</p>';
        } else {
            fnListEl.innerHTML = routines.map(r => {
                const name = typeof r === 'string' ? r : r.name;
                const prefix = r.class_name ? `🅼 ${escapeHtml(r.class_name)}.` : '🅵 ';
                const args = r.args && r.args.length ? `(${escapeHtml(r.args.join(', '))})` : '()';
                return `
                    <div style="padding: 0.35rem 0; border-bottom: 1px solid var(--border-color); font-family: var(--font-mono);">
                        <div style="font-weight: 500; color: #059669; font-size: 0.8rem;">
                            ${prefix}${escapeHtml(name)}${args}
                        </div>
                        ${r.line_start ? `<div style="font-size: 0.7rem; color: var(--text-muted);">line ${r.line_start}</div>` : ''}
                    </div>
                `;
            }).join('');
        }
    }

    // 3. Imports
    const imports = file.imports || [];
    const impCountEl = document.getElementById('exp-sym-imports-count');
    const impListEl = document.getElementById('exp-sym-imports-list');
    if (impCountEl) impCountEl.textContent = imports.length;
    if (impListEl) {
        if (imports.length === 0) {
            impListEl.innerHTML = '<p class="text-muted" style="margin:0;">No imports declared in this file.</p>';
        } else {
            impListEl.innerHTML = imports.map(imp => {
                const mod = imp.module || imp.imported_module || (typeof imp === 'string' ? imp : '');
                return `
                    <div style="padding: 0.3rem 0; border-bottom: 1px solid var(--border-color); font-family: var(--font-mono); font-size: 0.78rem;">
                        ${escapeHtml(mod)}
                        ${imp.imported_symbol ? `<span class="badge badge-secondary" style="margin-left: 4px; font-size: 0.65rem;">${escapeHtml(imp.imported_symbol)}</span>` : ''}
                    </div>
                `;
            }).join('');
        }
    }
}

/**
 * Jump directly to Code Explorer with target file selected.
 * @param {string} filePath
 * @param {Event} [e]
 */
function drillToFileInExplorer(filePath, e) {
    if (e) e.stopPropagation();
    if (!currentArchData) return;

    // Switch to Code Explorer tab
    switchArchTab('explorer', document.querySelector('.arch-nav-tab-btn[data-tab="explorer"]'));

    const subsystems = currentArchData.major_subsystems || (currentArchData.levels && currentArchData.levels.major_subsystems) || [];
    let targetSubIdx = 0;

    for (let i = 0; i < subsystems.length; i++) {
        const sub = subsystems[i];
        if (sub.path === '(root)' && !filePath.includes('/')) {
            targetSubIdx = i;
            break;
        } else if (filePath === sub.path || filePath.startsWith(sub.path + '/')) {
            targetSubIdx = i;
            break;
        } else if ((sub.key_files || []).some(k => k.path === filePath)) {
            targetSubIdx = i;
            break;
        }
    }

    const compSelect = document.getElementById('explorer-component-select');
    if (compSelect) {
        compSelect.value = String(targetSubIdx);
        onExplorerComponentChange(String(targetSubIdx));
    }

    const fileSelect = document.getElementById('explorer-file-select');
    if (fileSelect) {
        fileSelect.value = filePath;
        onExplorerFileChange(filePath);
    }
}

/**
 * Backward Compatibility Stubs
 */
function triggerArchRefresh() {
    if (currentArchRepo) loadArchitectureData(currentArchRepo, true);
}
function renderArchCardDiagram(data) { renderCleanArchitectureOverview(data); }
function renderArchMajorComponents() {}
function renderArchModulesTree() {}
function renderArchDependencies() {}
function initArchCodeExplorer() {}
function loadExplorerFile() {}
function renderArchCycles() {}
function renderArchHubs() {}
function renderArchEntryPoints() {}
function renderArchSummary() {}
function inspectArchSubsystem(name) {}
function inspectArchKeyFile(path) { drillToFileInExplorer(path); }


/**
 * Initialize dedicated Semantic Code Graph technical page.
 */
async function initSemanticGraphPage() {
    const canvas = document.getElementById('semantic-graph-canvas');
    if (!canvas) return;

    const params = new URLSearchParams(window.location.search);
    const repoParam = params.get('repo');
    if (!repoParam) return;

    try {
        const response = await fetch(`/api/repositories/graph/${encodeURIComponent(repoParam)}`);
        const res = await response.json();
        if (res.success && res.graph) {
            graphNodes = (res.graph.nodes || []).map((n, i) => {
                const angle = (2 * Math.PI * i) / (res.graph.nodes.length || 1);
                const r = 250 + (i % 5) * 60;
                return {
                    id: n.id,
                    name: n.name || n.id,
                    label: n.label || n.name || n.id,
                    type: n.type || 'entity',
                    x: Math.cos(angle) * r,
                    y: Math.sin(angle) * r,
                    radius: n.type === 'file' ? 16 : n.type === 'class' ? 14 : 10,
                    color: n.type === 'file' ? '#3b82f6' : n.type === 'class' ? '#a855f7' : n.type === 'package' ? '#f59e0b' : '#10b981',
                    data: n
                };
            });
            graphEdges = res.graph.edges || [];
            initGraph();
        }
    } catch (err) {
        console.error('Failed to load semantic graph on graph page:', err);
    }
}

// ==============================================================================
// Phase 1 Final Review: AI Project Report Generator Controller
// ==============================================================================

let currentReportData = null;
let currentReportRepo = null;

/**
 * Initialize AI Project Report Generator on the /report route.
 */
async function initReportPage() {
    const reportPage = document.querySelector('.report-page');
    if (!reportPage) return; // Not on the report page

    await populateReportRepoDropdown();

    const urlParams = new URLSearchParams(window.location.search);
    const repoParam = urlParams.get('repo');

    if (repoParam) {
        setReportRepoSelection(repoParam);
        await loadReport(repoParam, false);
    } else {
        let fallbackRepo = null;
        try {
            const stored = localStorage.getItem('codelens_last_repo');
            if (stored) fallbackRepo = stored;
        } catch (e) {}

        if (fallbackRepo) {
            setReportRepoSelection(fallbackRepo);
            await loadReport(fallbackRepo, false);
        } else {
            // Default candidate if available
            setReportRepoSelection('psf/requests');
            await loadReport('psf/requests', false);
        }
    }
}

/**
 * Populate repository select dropdown with previously analyzed and cached repositories.
 */
async function populateReportRepoDropdown() {
    const select = document.getElementById('report-repo-select');
    if (!select) return;

    try {
        const [archRes, repRes] = await Promise.all([
            fetch('/api/repositories/analysis/cached').then(r => r.json()).catch(() => ({})),
            fetch('/api/repositories/report/cached').then(r => r.json()).catch(() => ({}))
        ]);

        const reposSet = new Set();
        (archRes.repositories || []).forEach(r => {
            if (r.full_name) reposSet.add(r.full_name);
            else if (r.owner && r.name) reposSet.add(`${r.owner}/${r.name}`);
        });
        (repRes.reports || []).forEach(r => {
            if (r.full_name) reposSet.add(r.full_name);
        });

        // Ensure real sample candidate repos are in list
        ['psf/requests', 'bottlepy/bottle', 'pallets/flask', 'fastapi/fastapi'].forEach(r => reposSet.add(r));

        select.innerHTML = '<option value="">-- Choose an analyzed repository --</option>';
        Array.from(reposSet).sort().forEach(r => {
            const opt = document.createElement('option');
            opt.value = r;
            opt.textContent = r;
            select.appendChild(opt);
        });
    } catch (err) {
        console.error('Error populating report repo dropdown:', err);
    }
}

function setReportRepoSelection(repoName) {
    currentReportRepo = repoName;
    const select = document.getElementById('report-repo-select');
    const input = document.getElementById('report-repo-input');
    if (select) select.value = repoName;
    if (input) input.value = repoName;
}

function onReportRepoSelected(repoVal) {
    if (!repoVal) return;
    const input = document.getElementById('report-repo-input');
    if (input) input.value = repoVal;
    loadReport(repoVal, false);
}

async function triggerGenerateReport() {
    const input = document.getElementById('report-repo-input');
    const select = document.getElementById('report-repo-select');
    let repoVal = (input && input.value ? input.value.trim() : '') || (select && select.value ? select.value.trim() : '');

    if (!repoVal) {
        showToast('Repository Required', 'Please enter or select a repository (e.g. psf/requests)', 'warning');
        return;
    }

    await loadReport(repoVal, true);
}

async function loadReport(repoInput, forceRefresh = false) {
    if (!repoInput) return;
    currentReportRepo = repoInput.trim();

    try {
        localStorage.setItem('codelens_last_repo', currentReportRepo);
    } catch (e) {}

    const loadingEl = document.getElementById('report-loading');
    const placeholderEl = document.getElementById('report-placeholder');
    const displayWrap = document.getElementById('report-display-wrap');
    const exportActions = document.getElementById('report-export-actions');
    const statusBanner = document.getElementById('report-status-banner');

    if (loadingEl) loadingEl.style.display = 'block';
    if (placeholderEl) placeholderEl.style.display = 'none';

    try {
        const response = await fetch('/api/repositories/report', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                repo: currentReportRepo,
                force_refresh: forceRefresh
            })
        });

        const res = await response.json();
        if (!response.ok || !res.success) {
            throw new Error(res.error || 'Failed to generate report.');
        }

        currentReportData = res.report || res.data || res;
        renderFullReport(currentReportData);
        if (currentReportData.repository && currentReportData.repository.full_name) {
            syncNavigationRepoParams(currentReportData.repository.full_name);
        }

        if (displayWrap) displayWrap.style.display = 'block';
        if (exportActions) exportActions.style.display = 'flex';
        if (statusBanner) {
            statusBanner.style.display = 'flex';
            statusBanner.style.background = 'rgba(16, 185, 129, 0.15)';
            statusBanner.style.border = '1px solid #10b981';
            const statusTxt = document.getElementById('report-status-text');
            if (statusTxt) statusTxt.textContent = `Report generated successfully (${currentReportData.statistics.total_files} files, ${currentReportData.statistics.total_classes} classes, 16 sections).`;
            const timeBadge = document.getElementById('report-timestamp-badge');
            if (timeBadge) timeBadge.textContent = new Date().toLocaleTimeString();
        }

        // Configure Download Links
        const repo = currentReportData.repository;
        const btnMd = document.getElementById('btn-download-md');
        const btnHtml = document.getElementById('btn-download-html');
        if (btnMd) btnMd.href = `/api/repositories/report/${encodeURIComponent(repo.owner)}/${encodeURIComponent(repo.name)}/download?format=md`;
        if (btnHtml) btnHtml.href = `/api/repositories/report/${encodeURIComponent(repo.owner)}/${encodeURIComponent(repo.name)}/download?format=html`;

        // Update URL query parameter
        const newUrl = `${window.location.pathname}?repo=${encodeURIComponent(repo.full_name)}`;
        window.history.pushState({ path: newUrl }, '', newUrl);

        showToast('Report Ready', `Generated factual project report for ${repo.full_name}`, 'success');

    } catch (err) {
        console.error('[CodeLens AI] Report generation error:', err);
        showToast('Report Notice', 'Unable to generate the report. Please try again.', 'error');
        if (placeholderEl && (!currentReportData || !displayWrap || displayWrap.style.display === 'none')) {
            placeholderEl.style.display = 'block';
        }
    } finally {
        if (loadingEl) loadingEl.style.display = 'none';
    }
}

function scrollToReportView() {
    const wrap = document.getElementById('report-display-wrap');
    if (wrap) wrap.scrollIntoView({ behavior: 'smooth' });
}

function printReport() {
    window.print();
}

function renderFullReport(data) {
    if (!data) return;
    const repo = data.repository || (data.project_overview && data.project_overview.repository) || {};
    const stats = data.statistics || (data.technical_analysis && data.technical_analysis.metrics) || (data.repository_summary && data.repository_summary.statistics) || {};
    const sec1Data = data.project_overview || data.overview || {};
    const sec2Data = data.what_project_does || {};
    const sec3Data = data.how_project_works || {};
    const sec4Data = data.architecture_overview || {};
    const sec5Data = data.major_components || {};
    const sec6Data = data.important_files || {};
    const sec7Data = data.classes_section || {};
    const sec8Data = data.functions_and_methods || {};
    const sec9Data = data.dependencies_and_relationships || {};
    const sec10Data = data.architecture_relationships || data.component_relations || {};
    const sec11Data = data.for_new_developer || {};
    const sec12Data = data.technical_analysis || data.repository_summary || {};
    const sec13Data = data.code_graph_summary || data.semantic_graph_summary || {};
    const sec14Data = data.observations || [];
    const sec15Data = data.conclusion || '';

    // Update related tools navigation links
    const repoParam = encodeURIComponent(repo.full_name || '');
    const setLink = (id, href) => {
        const el = document.getElementById(id);
        if (el) el.href = href;
    };
    if (repo.full_name) {
        setLink('btn-top-arch', `/architecture?repo=${repoParam}`);
        setLink('btn-top-graph', `/graph?repo=${repoParam}`);
        setLink('btn-top-chat', `/chat?repo=${repoParam}`);
        setLink('btn-rel-arch', `/architecture?repo=${repoParam}`);
        setLink('btn-rel-graph', `/graph?repo=${repoParam}`);
        setLink('btn-rel-chat', `/chat?repo=${repoParam}`);
        setLink('btn-sec4-arch', `/architecture?repo=${repoParam}`);
        setLink('btn-sec13-graph', `/graph?repo=${repoParam}`);
    }

    // Breadcrumb and Header
    const bcRepo = document.getElementById('report-breadcrumb-repo');
    if (bcRepo) bcRepo.textContent = repo.full_name || 'Report';

    const titleEl = document.getElementById('rep-repo-title');
    const linkEl = document.getElementById('rep-github-link');
    const descEl = document.getElementById('rep-repo-desc');
    const langEl = document.getElementById('rep-primary-lang');
    const cycleBadge = document.getElementById('rep-cycle-badge');
    const dateEl = document.getElementById('rep-generated-date');

    if (titleEl) titleEl.textContent = `${repo.full_name || 'Repository'} – Project Report`;
    if (linkEl) linkEl.href = repo.url || (repo.full_name ? `https://github.com/${repo.full_name}` : '#');
    if (descEl) descEl.textContent = repo.description || 'No description provided.';
    if (langEl) langEl.textContent = repo.primary_language || 'Codebase';
    if (dateEl) dateEl.textContent = sec1Data.generated_at || repo.analyzed_at || new Date().toISOString();

    if (cycleBadge) {
        if (stats.cycles_count > 0) {
            cycleBadge.textContent = `${stats.cycles_count} Cycles Detected`;
            cycleBadge.className = 'badge badge-warning';
        } else {
            cycleBadge.textContent = 'No detected dependency cycles';
            cycleBadge.className = 'badge badge-success';
        }
    }

    // Section 1: Project Overview
    const sec1Text = document.getElementById('sec-1-text');
    if (sec1Text) sec1Text.textContent = sec1Data.summary || '';

    const sec1Content = document.getElementById('sec-1-content');
    if (sec1Content) {
        const r = sec1Data.repository || repo;
        sec1Content.innerHTML = `
            <table class="data-table" style="width:100%; font-size:0.875rem;">
                <tr><th style="width:25%">Property</th><th>Value</th></tr>
                <tr><td>Repository Name</td><td><strong>${escapeHtml(r.name || '')}</strong></td></tr>
                <tr><td>Owner</td><td>${escapeHtml(r.owner || '')}</td></tr>
                <tr><td>GitHub URL</td><td><a href="${escapeHtml(r.url || '')}" target="_blank" rel="noopener noreferrer">${escapeHtml(r.url || '')}</a></td></tr>
                <tr><td>Primary Language</td><td><span class="badge badge-info">${escapeHtml(r.primary_language || '')}</span></td></tr>
                <tr><td>Description</td><td>${escapeHtml(r.description || 'N/A')}</td></tr>
                <tr><td>Branch / Commit</td><td><code>${escapeHtml(r.branch || 'default')}</code> (${escapeHtml(r.commit || 'HEAD')})</td></tr>
                <tr><td>Analysis Timestamp</td><td>${escapeHtml(r.analyzed_at || sec1Data.generated_at || '')}</td></tr>
                <tr><td>Analysis Engine</td><td><span class="badge badge-secondary">${escapeHtml(sec1Data.system_version || 'CodeLens AI v1.0')}</span></td></tr>
            </table>
        `;
    }

    // Section 2: What Does This Project Do?
    const sec2 = document.getElementById('sec-2-content');
    if (sec2) {
        const prob = sec2Data.problem_solved || '';
        const aud = sec2Data.target_audience || '';
        const purp = sec2Data.main_purpose || '';
        const sum = sec2Data.summary || '';

        sec2.innerHTML = `
            <div style="background:var(--bg-tertiary); padding:1.25rem; border-radius:var(--radius-sm); border-left:3px solid var(--accent-primary); margin-bottom:1.25rem;">
                <p style="margin:0; font-size:0.95rem; line-height:1.7;">${escapeHtml(sum || prob || 'Project provides modular software components for developers.')}</p>
            </div>
            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:1rem;">
                <div style="background:var(--bg-surface); padding:1rem; border-radius:var(--radius-sm); border:1px solid var(--border-color);">
                    <div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:var(--accent-primary); margin-bottom:0.35rem;">Problem Solved</div>
                    <p style="margin:0; font-size:0.875rem; color:var(--text-secondary); line-height:1.6;">${escapeHtml(prob || 'Addresses domain complexity and protocol abstractions.')}</p>
                </div>
                <div style="background:var(--bg-surface); padding:1rem; border-radius:var(--radius-sm); border:1px solid var(--border-color);">
                    <div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:var(--accent-primary); margin-bottom:0.35rem;">Target Audience &amp; Use Cases</div>
                    <p style="margin:0; font-size:0.875rem; color:var(--text-secondary); line-height:1.6;">${escapeHtml(aud || 'Software developers and applications integrating this library.')}</p>
                </div>
                <div style="background:var(--bg-surface); padding:1rem; border-radius:var(--radius-sm); border:1px solid var(--border-color);">
                    <div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:var(--accent-primary); margin-bottom:0.35rem;">Main Purpose</div>
                    <p style="margin:0; font-size:0.875rem; color:var(--text-secondary); line-height:1.6;">${escapeHtml(purp || 'Provides high quality abstractions and reusable domain code.')}</p>
                </div>
            </div>
        `;
    }

    // Section 3: How Does the Project Work?
    const sec3 = document.getElementById('sec-3-content');
    if (sec3) {
        const flowSum = sec3Data.flow_summary || 'Execution moves from public API callers through domain controllers and internal utilities to return outputs.';
        const stages = sec3Data.stages || [];
        const diagram = sec3Data.flow_diagram || '[ User / App ] ──> [ Public API ] ──> [ Core Processing ] ──> [ Utilities ] ──> [ Result ]';

        sec3.innerHTML = `
            <p style="line-height:1.7; font-size:0.95rem; margin-bottom:1rem;">${escapeHtml(flowSum)}</p>
            <div style="background:#090d16; padding:1rem 1.25rem; border-radius:var(--radius-sm); border:1px solid var(--border-color); font-family:var(--font-mono); font-size:0.8125rem; color:#38bdf8; overflow-x:auto; margin-bottom:1.5rem; text-align:center;">
                ${escapeHtml(diagram)}
            </div>
            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:0.75rem;">
                ${stages.map(st => `
                    <div style="background:var(--bg-surface); padding:1rem; border-radius:var(--radius-sm); border:1px solid var(--border-color);">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.5rem;">
                            <span class="badge badge-primary">Stage ${st.step}</span>
                            <span style="font-size:0.75rem; color:var(--text-muted); font-weight:600;">${escapeHtml(st.role)}</span>
                        </div>
                        <h4 style="margin:0 0 0.35rem 0; font-size:0.95rem; color:var(--text-primary);">${escapeHtml(st.name)}</h4>
                        <p style="margin:0; font-size:0.8125rem; color:var(--text-secondary); line-height:1.5;">${escapeHtml(st.explanation)}</p>
                    </div>
                `).join('')}
            </div>
        `;
    }

    // Section 4: Architecture Overview
    const sec4 = document.getElementById('sec-4-content');
    if (sec4) {
        const pattern = sec4Data.architectural_pattern || 'Modular Subsystem Architecture';
        const subCount = sec4Data.subsystem_count || (sec4Data.major_subsystems_summary || []).length || 0;
        const mod = sec4Data.modularity_metrics || data.code_structure || {};
        const bullets = sec4Data.summary_bullets || [];

        sec4.innerHTML = `
            <div style="display:flex; gap:1rem; flex-wrap:wrap; align-items:center; margin-bottom:1.25rem;">
                <div><strong>Pattern:</strong> <span class="badge badge-primary" style="font-size:0.85rem;">${escapeHtml(pattern)}</span></div>
                <div><strong>Subsystems:</strong> <span class="badge badge-info">${subCount} Partitioned Subsystems</span></div>
            </div>

            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:0.75rem; margin-bottom:1.25rem;">
                <div style="background:var(--bg-tertiary); padding:0.75rem; border-radius:var(--radius-sm); border:1px solid var(--border-color); text-align:center;">
                    <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Avg Methods / Class</div>
                    <div style="font-size:1.25rem; font-weight:700; color:var(--accent-primary);">${mod.avg_methods_per_class || 0}</div>
                </div>
                <div style="background:var(--bg-tertiary); padding:0.75rem; border-radius:var(--radius-sm); border:1px solid var(--border-color); text-align:center;">
                    <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Avg Functions / File</div>
                    <div style="font-size:1.25rem; font-weight:700; color:var(--accent-primary);">${mod.avg_functions_per_file || 0}</div>
                </div>
                <div style="background:var(--bg-tertiary); padding:0.75rem; border-radius:var(--radius-sm); border:1px solid var(--border-color); text-align:center;">
                    <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Class / Function Ratio</div>
                    <div style="font-size:1.25rem; font-weight:700; color:var(--accent-primary);">${mod.class_to_function_ratio || 0}</div>
                </div>
            </div>

            <h4 style="margin: 1rem 0 0.5rem 0; font-size:0.95rem; color:var(--text-primary);">Architectural Structure Highlights</h4>
            <ul style="line-height:1.7; font-size:0.9rem; padding-left:1.25rem; margin:0;">
                ${bullets.map(b => `<li>${escapeHtml(b)}</li>`).join('')}
            </ul>
        `;
    }

    // Section 5: Main Components
    const sec5 = document.getElementById('sec-5-content');
    if (sec5) {
        const components = sec5Data.components || (data.architecture_overview && data.architecture_overview.major_subsystems_summary) || [];
        if (components.length === 0) {
            sec5.innerHTML = '<p class="text-muted" style="font-size:0.875rem;">No subsystem components identified.</p>';
        } else {
            sec5.innerHTML = `
                <table class="data-table" style="width:100%; font-size:0.8125rem;">
                    <thead><tr><th>Component</th><th>Category</th><th>Architectural Responsibility</th><th>Files</th><th>Key Files</th></tr></thead>
                    <tbody>
                        ${components.map(c => {
                            const kfiles = (c.key_files || []).map(kf => {
                                const fn = typeof kf === 'object' ? (kf.name || kf.path) : kf;
                                return `<code style="font-size:0.75rem; margin-right:4px;">${escapeHtml(fn)}</code>`;
                            }).join(' ');
                            return `
                                <tr>
                                    <td><strong>${escapeHtml(c.icon || '📁')} ${escapeHtml(c.name || c.short_name || '')}</strong></td>
                                    <td><span class="badge badge-secondary">${escapeHtml(c.category || 'Module')}</span></td>
                                    <td>${escapeHtml(c.description || c.role || 'Component')}</td>
                                    <td><strong>${c.files_count || c.file_count || 0}</strong></td>
                                    <td>${kfiles || '<span class="text-muted">None</span>'}</td>
                                </tr>
                            `;
                        }).join('')}
                    </tbody>
                </table>
            `;
        }
    }

    // Section 6: Important Files
    const sec6 = document.getElementById('sec-6-content');
    if (sec6) {
        const prodFiles = sec6Data.production_files || sec6Data.files || [];
        const testHubs = sec6Data.test_hubs || [];
        if (prodFiles.length === 0 && testHubs.length === 0) {
            sec6.innerHTML = '<p class="text-muted" style="font-size:0.875rem;">No files evaluated.</p>';
        } else {
            let html = `
                <h4 style="margin: 0 0 0.5rem 0; font-size:0.95rem; color:var(--text-primary);">Primary Production Source Files</h4>
                <table class="data-table" style="width:100%; font-size:0.8125rem; margin-bottom:1.5rem;">
                    <thead><tr><th>File Path</th><th>Role</th><th>Purpose / Significance</th><th>Metrics</th></tr></thead>
                    <tbody>
                        ${prodFiles.map(f => `
                            <tr>
                                <td><code>${escapeHtml(f.path)}</code></td>
                                <td><span class="badge ${f.is_entry_point ? 'badge-warning' : (f.is_hub ? 'badge-primary' : 'badge-info')}">${escapeHtml(f.role)}</span></td>
                                <td style="font-size:0.8rem; line-height:1.5;">${escapeHtml(f.purpose || f.rationale || 'Key source module')}</td>
                                <td>${f.classes_count} cls / ${f.functions_count} fn</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;
            if (testHubs.length > 0) {
                html += `
                    <h4 style="margin: 1.25rem 0 0.5rem 0; font-size:0.95rem; color:var(--text-primary);">Important Test Hubs (Verification Architecture)</h4>
                    <table class="data-table" style="width:100%; font-size:0.8125rem;">
                        <thead><tr><th>File Path</th><th>Role</th><th>Purpose / Verification Target</th><th>Metrics</th></tr></thead>
                        <tbody>
                            ${testHubs.map(f => `
                                <tr>
                                    <td><code>${escapeHtml(f.path)}</code></td>
                                    <td><span class="badge badge-secondary">${escapeHtml(f.role || 'Test Hub')}</span></td>
                                    <td style="font-size:0.8rem; line-height:1.5;">${escapeHtml(f.purpose || f.rationale || 'Automated test suite module')}</td>
                                    <td>${f.classes_count} cls / ${f.functions_count} fn</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                `;
            }
            sec6.innerHTML = html;
        }
    }

    // Section 7: Important Classes
    const sec7 = document.getElementById('sec-7-content');
    if (sec7) {
        const classes = sec7Data.classes || data.classes || [];
        if (classes.length === 0) {
            sec7.innerHTML = '<p class="text-muted" style="font-size:0.875rem;">No classes declared in the analyzed repository.</p>';
        } else {
            sec7.innerHTML = `
                <table class="data-table" style="width:100%; font-size:0.8125rem;">
                    <thead><tr><th>Class Name</th><th>Declaring File</th><th>Methods</th><th>What It Does / Purpose</th></tr></thead>
                    <tbody>
                        ${classes.slice(0, 40).map(c => `
                            <tr>
                                <td><strong><code>${escapeHtml(c.name)}</code></strong></td>
                                <td><code>${escapeHtml(c.file)}</code></td>
                                <td>${c.methods_count}</td>
                                <td>${escapeHtml(c.purpose || c.docstring || 'Domain class definition')}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;
        }
    }

    // Section 8: Important Functions / Methods
    const sec8 = document.getElementById('sec-8-content');
    if (sec8) {
        const funcs = sec8Data.sample_functions || data.functions || [];
        const methods = sec8Data.sample_methods || data.methods || [];
        sec8.innerHTML = `
            <h4 style="margin: 0 0 0.5rem 0; font-size:0.95rem; color:var(--text-primary);">
                Top-Level Functions (${sec8Data.total_functions || funcs.length} total)
            </h4>
            ${funcs.length === 0 ? '<p class="text-muted" style="font-size:0.875rem;">No top-level functions declared.</p>' : `
                <table class="data-table" style="width:100%; font-size:0.8125rem; margin-bottom:1.5rem;">
                    <thead><tr><th>Function Name</th><th>File</th><th>Parameters</th><th>Purpose</th></tr></thead>
                    <tbody>
                        ${funcs.slice(0, 30).map(fn => `
                            <tr>
                                <td><strong><code>${escapeHtml(fn.name)}()</code></strong></td>
                                <td><code>${escapeHtml(fn.file)}</code></td>
                                <td><code>(${escapeHtml((fn.parameters || []).join(', '))})</code></td>
                                <td>${escapeHtml(fn.purpose || fn.docstring || 'Routine')}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `}

            <h4 style="margin: 1rem 0 0.5rem 0; font-size:0.95rem; color:var(--text-primary);">
                Class-Bound Methods (${sec8Data.total_methods || methods.length} total)
            </h4>
            ${methods.length === 0 ? '<p class="text-muted" style="font-size:0.875rem;">No methods declared.</p>' : `
                <table class="data-table" style="width:100%; font-size:0.8125rem;">
                    <thead><tr><th>Method Name</th><th>Bound Class</th><th>File</th><th>Parameters</th><th>Return Type</th></tr></thead>
                    <tbody>
                        ${methods.slice(0, 30).map(m => `
                            <tr>
                                <td><strong><code>${escapeHtml(m.name)}()</code></strong></td>
                                <td><code>${escapeHtml(m.class_name)}</code></td>
                                <td><code>${escapeHtml(m.file)}</code></td>
                                <td><code>(${escapeHtml((m.parameters || []).join(', '))})</code></td>
                                <td><code>${escapeHtml(m.return_type || 'None')}</code></td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `}
        `;
    }

    // Section 9: Dependencies
    const sec9 = document.getElementById('sec-9-content');
    if (sec9) {
        const intCount = sec9Data.internal_imports_count || 0;
        const extCount = sec9Data.external_imports_count || 0;
        const stdCount = sec9Data.stdlib_imports_count || 0;
        const extPackages = sec9Data.external_packages || data.dependencies || [];
        const stdlibMods = sec9Data.stdlib_modules || [];

        sec9.innerHTML = `
            <div style="display:flex; gap:1.5rem; flex-wrap:wrap; margin-bottom:1rem; font-size:0.875rem;">
                <div><strong>Internal Module Imports:</strong> ${intCount}</div>
                <div><strong>External Package Imports:</strong> ${extCount}</div>
                <div><strong>Standard Library Imports:</strong> ${stdCount}</div>
            </div>

            <h4 style="margin: 1rem 0 0.5rem 0; font-size:0.95rem; color:var(--text-primary);">Third-Party External Packages</h4>
            ${extPackages.length === 0 ? '<p class="text-muted" style="font-size:0.875rem;">No external dependencies detected.</p>' : `
                <table class="data-table" style="width:100%; font-size:0.8125rem; margin-bottom:1.5rem;">
                    <thead><tr><th>Package Name</th><th>Purpose / Why Used</th><th>Occurrences</th><th>Dependent Files</th></tr></thead>
                    <tbody>
                        ${extPackages.slice(0, 30).map(d => `
                            <tr>
                                <td><strong><code>${escapeHtml(d.name)}</code></strong></td>
                                <td>${escapeHtml(d.purpose || d.description || 'External capability provider')}</td>
                                <td>${d.occurrences}</td>
                                <td>${d.files_count} files</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `}

            ${stdlibMods.length > 0 ? `
                <h4 style="margin: 1rem 0 0.5rem 0; font-size:0.95rem; color:var(--text-primary);">Standard Library Modules</h4>
                <div style="display:flex; gap:0.4rem; flex-wrap:wrap;">
                    ${stdlibMods.slice(0, 25).map(s => `
                        <span class="badge badge-secondary" style="font-size:0.75rem;" title="${escapeHtml(s.purpose || '')}">
                            <code>${escapeHtml(s.name)}</code> (${s.occurrences})
                        </span>
                    `).join('')}
                </div>
            ` : ''}
        `;
    }

    // Section 10: How the Components Relate
    const sec10 = document.getElementById('sec-10-content');
    if (sec10) {
        const narrative = sec10Data.narrative || 'Top-level API modules coordinate operations through central hub processors, utilizing utility routines and external dependencies.';
        const flows = sec10Data.component_flows || [];
        const dirFlows = sec10Data.directory_flows || [];

        sec10.innerHTML = `
            <div style="background:var(--bg-tertiary); padding:1rem; border-radius:var(--radius-sm); border-left:3px solid var(--accent-primary); margin-bottom:1.25rem;">
                <p style="margin:0; font-size:0.925rem; line-height:1.7;">${escapeHtml(narrative)}</p>
            </div>

            <h4 style="margin: 1rem 0 0.5rem 0; font-size:0.95rem; color:var(--text-primary);">Inter-Subsystem / Component Interaction Flows</h4>
            ${flows.length > 0 ? `
                <table class="data-table" style="width:100%; font-size:0.8125rem;">
                    <thead><tr><th>Source Subsystem</th><th>Flow</th><th>Target Subsystem</th><th>Relationships</th></tr></thead>
                    <tbody>
                        ${flows.map(fl => `
                            <tr>
                                <td><strong>${escapeHtml(fl.source)}</strong></td>
                                <td style="color:var(--accent-primary);">&rarr;</td>
                                <td><strong>${escapeHtml(fl.target)}</strong></td>
                                <td><span class="badge badge-info">${fl.relationship_count} relationships</span></td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            ` : (dirFlows.length > 0 ? `
                <table class="data-table" style="width:100%; font-size:0.8125rem;">
                    <thead><tr><th>Source Directory</th><th>Flow</th><th>Target Directory</th><th>Dependencies</th></tr></thead>
                    <tbody>
                        ${dirFlows.map(df => `
                            <tr>
                                <td><code>${escapeHtml(df.from || df.source)}</code></td>
                                <td style="color:var(--accent-primary);">&rarr;</td>
                                <td><code>${escapeHtml(df.to || df.target)}</code></td>
                                <td><span class="badge badge-info">${df.count || df.relationship_count || 1}</span></td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            ` : '<p class="text-muted" style="font-size:0.875rem;">Direct modular imports between root files.</p>')}
        `;
    }

    // Section 11: For a New Developer (Onboarding Guide)
    const sec11 = document.getElementById('sec-11-content');
    if (sec11) {
        const startHere = sec11Data.start_here || 'main.py';
        const readingOrder = sec11Data.reading_order || [];
        const entryNote = sec11Data.executable_entry_points_note || '';
        const testsLoc = sec11Data.tests_location || 'Look for tests in the tests/ directory.';
        const safeExploration = sec11Data.safe_exploration || 'Run tests before making changes and add new tests for your modifications.';

        sec11.innerHTML = `
            <div style="background:var(--bg-tertiary); padding:1rem; border-radius:var(--radius-sm); border-left:3px solid var(--accent-primary); margin-bottom:1.25rem;">
                <p style="margin:0 0 0.25rem 0; font-size:0.95rem;"><strong>Start Here:</strong> Begin your codebase exploration at <code>${escapeHtml(startHere)}</code> to understand how calls are initiated and dispatched.</p>
                ${entryNote ? `<p style="margin:0.25rem 0 0 0; font-size:0.8125rem; color:var(--text-secondary); font-style:italic;">${escapeHtml(entryNote)}</p>` : ''}
            </div>

            <h4 style="margin: 1rem 0 0.5rem 0; font-size:0.95rem; color:var(--text-primary);">Recommended File Reading Order</h4>
            ${readingOrder.length > 0 ? `
                <table class="data-table" style="width:100%; font-size:0.8125rem; margin-bottom:1.25rem;">
                    <thead><tr><th>Step</th><th>File</th><th>Role</th><th>Exploration Guidance</th></tr></thead>
                    <tbody>
                        ${readingOrder.map(item => `
                            <tr>
                                <td><span class="badge badge-primary">Step ${item.step}</span></td>
                                <td><code>${escapeHtml(item.file)}</code></td>
                                <td><span class="badge badge-secondary">${escapeHtml(item.role)}</span></td>
                                <td>${escapeHtml(item.guidance)}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            ` : ''}

            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:1rem;">
                <div style="background:var(--bg-surface); padding:1rem; border-radius:var(--radius-sm); border:1px solid var(--border-color);">
                    <div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:var(--accent-primary); margin-bottom:0.35rem;">Automated Verification</div>
                    <p style="margin:0; font-size:0.85rem; color:var(--text-secondary); line-height:1.6;">${escapeHtml(testsLoc)}</p>
                </div>
                <div style="background:var(--bg-surface); padding:1rem; border-radius:var(--radius-sm); border:1px solid var(--border-color);">
                    <div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:var(--accent-primary); margin-bottom:0.35rem;">Safe Code Exploration</div>
                    <p style="margin:0; font-size:0.85rem; color:var(--text-secondary); line-height:1.6; white-space:pre-line;">${escapeHtml(safeExploration)}</p>
                </div>
            </div>
        `;
    }

    // Section 12: Technical Analysis (Appendix / Deep Dive)
    const sec12 = document.getElementById('sec-12-content');
    const sec12Tree = document.getElementById('sec-12-tree');
    if (sec12) {
        const m = sec12Data.metrics || stats;
        const langs = sec12Data.languages || data.languages || [];
        const eps = sec12Data.entry_points || data.entry_points || [];

        sec12.innerHTML = `
            <div class="arch-stats-grid" style="margin-bottom: 1.5rem;">
                <div class="arch-stat-card"><div class="arch-stat-label">Files</div><div class="arch-stat-value">${Number(m.total_files || 0).toLocaleString()}</div></div>
                <div class="arch-stat-card"><div class="arch-stat-label">Directories</div><div class="arch-stat-value">${Number(m.total_directories || 0).toLocaleString()}</div></div>
                <div class="arch-stat-card"><div class="arch-stat-label">Classes</div><div class="arch-stat-value">${Number(m.total_classes || 0).toLocaleString()}</div></div>
                <div class="arch-stat-card"><div class="arch-stat-label">Functions</div><div class="arch-stat-value">${Number(m.total_functions || 0).toLocaleString()}</div></div>
                <div class="arch-stat-card"><div class="arch-stat-label">Methods</div><div class="arch-stat-value">${Number(m.total_methods || 0).toLocaleString()}</div></div>
                <div class="arch-stat-card"><div class="arch-stat-label">Code Size</div><div class="arch-stat-value" style="font-size:1.1rem;">${escapeHtml(m.total_code_size_formatted || 'N/A')}</div></div>
            </div>

            <h4 style="margin: 1rem 0 0.5rem 0; font-size:0.95rem; color:var(--text-primary);">Language Composition</h4>
            <table class="data-table" style="width:100%; font-size:0.8125rem; margin-bottom:1.5rem;">
                <thead><tr><th>Language</th><th>Files Count</th><th>Code Size</th><th>Percentage</th></tr></thead>
                <tbody>
                    ${langs.map(l => `
                        <tr>
                            <td><strong>${escapeHtml(l.language)}</strong></td>
                            <td>${l.files_count}</td>
                            <td>${escapeHtml(l.size_formatted)}</td>
                            <td><span class="badge badge-primary">${l.percentage}%</span></td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>

            ${eps.length > 0 ? `
                <h4 style="margin: 1rem 0 0.5rem 0; font-size:0.95rem; color:var(--text-primary);">Detected Entry Points</h4>
                <table class="data-table" style="width:100%; font-size:0.8125rem; margin-bottom:1.5rem;">
                    <thead><tr><th>Entry File</th><th>Symbol</th><th>Line</th><th>Detection Evidence</th></tr></thead>
                    <tbody>
                        ${eps.map(ep => `
                            <tr>
                                <td><code>${escapeHtml(ep.file)}</code></td>
                                <td><strong><code>${escapeHtml(ep.symbol)}</code></strong></td>
                                <td>${ep.line || 'N/A'}</td>
                                <td>${escapeHtml(ep.detection_reason)}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            ` : ''}

            <h4 style="margin: 1rem 0 0.5rem 0; font-size:0.95rem; color:var(--text-primary);">Directory Hierarchy</h4>
        `;
    }
    if (sec12Tree) {
        sec12Tree.textContent = sec12Data.directory_tree || data.directory_structure || 'Tree structure not available.';
    }

    // Section 13: Semantic Code Graph Summary
    const sec13 = document.getElementById('sec-13-content');
    if (sec13) {
        const totalNodes = sec13Data.total_nodes || stats.graph_nodes || 0;
        const totalEdges = sec13Data.total_edges || stats.graph_edges || 0;
        const cyc = sec13Data.cycle_status || data.cycle_information || {};
        const isAcyclic = cyc.is_acyclic !== undefined ? cyc.is_acyclic : (stats.cycles_count === 0);
        const nodeTypes = sec13Data.node_types || {};

        sec13.innerHTML = `
            <div style="display:flex; gap:1.5rem; flex-wrap:wrap; font-size:0.875rem; margin-bottom:0.75rem;">
                <div><strong>Total Graph Nodes:</strong> ${totalNodes}</div>
                <div><strong>Total Graph Edges:</strong> ${totalEdges}</div>
                <div><strong>Graph Topology:</strong> <span class="badge ${isAcyclic ? 'badge-success' : 'badge-warning'}">${isAcyclic ? 'No detected dependency cycles' : 'Cyclic Graph'}</span></div>
                <div><strong>Integrity:</strong> <span class="badge badge-success">Valid</span></div>
            </div>
            <p style="font-size:0.875rem; color:var(--text-secondary); margin-bottom:1rem; line-height:1.6;">
                ${escapeHtml(cyc.evaluation || 'All internal relationships form an acyclic graph.')}
            </p>
            ${Object.keys(nodeTypes).length > 0 ? `
                <div style="display:flex; gap:0.5rem; flex-wrap:wrap;">
                    ${Object.entries(nodeTypes).map(([type, cnt]) => `
                        <span class="badge badge-secondary" style="font-size:0.75rem;"><strong>${escapeHtml(type)}</strong>: ${cnt}</span>
                    `).join('')}
                </div>
            ` : ''}
        `;
    }

    // Section 14: Observations and Limitations
    const sec14 = document.getElementById('sec-14-list');
    if (sec14) {
        const obs = Array.isArray(sec14Data) ? sec14Data : (data.observations || []);
        sec14.innerHTML = obs.map(o => `<li style="margin-bottom:0.5rem;">${escapeHtml(o)}</li>`).join('');
    }

    // Section 15: Conclusion
    const sec15 = document.getElementById('sec-15-text');
    if (sec15) {
        sec15.textContent = typeof sec15Data === 'string' ? sec15Data : (sec15Data.text || data.conclusion || '');
    }
}


/* ==============================================================================
   AI Repository Comprehension Assistant Chatbot Controller
   ============================================================================== */
let currentChatRepo = '';
let currentChatSessionId = '';

function generateSessionId() {
    return 'sess_' + Math.random().toString(36).substring(2, 11) + '_' + Date.now();
}

/**
 * Initialize AI Repository Assistant on /chat route.
 */
async function initChatPage() {
    const container = document.getElementById('chat-messages-container');
    if (!container) return; // Not on the chat page

    currentChatSessionId = generateSessionId();

    // 1. Populate repository dropdown
    await populateChatRepoSelector();

    // 2. Parse URL params for repo
    const urlParams = new URLSearchParams(window.location.search);
    const repoParam = urlParams.get('repo');

    let targetRepo = repoParam;
    if (!targetRepo) {
        try {
            targetRepo = localStorage.getItem('codelens_last_repo');
        } catch (e) {}
    }

    const select = document.getElementById('chat-repo-select');
    if (!targetRepo && select && select.options.length > 1) {
        targetRepo = select.options[1].value;
    }

    if (!targetRepo) {
        targetRepo = 'psf/requests';
    }

    if (targetRepo) {
        const emptyEl = document.getElementById('chat-empty-state');
        if (emptyEl) emptyEl.style.display = 'none';
        selectChatRepo(targetRepo);
    } else {
        const emptyEl = document.getElementById('chat-empty-state');
        if (emptyEl) emptyEl.style.display = 'block';
        const streamCard = document.querySelector('.chat-stream-card');
        if (streamCard) streamCard.style.display = 'none';
        const suggestSection = document.querySelector('.chat-suggested-section');
        if (suggestSection) suggestSection.style.display = 'none';
        const reportCta = document.getElementById('chat-report-cta');
        if (reportCta) reportCta.style.display = 'none';
    }

    // 3. Check LLM provider status
    checkLlmStatus();
}

/**
 * Populate repository select dropdown with analyzed repositories.
 */
async function populateChatRepoSelector() {
    const select = document.getElementById('chat-repo-select');
    if (!select) return;

    try {
        const [archRes, repRes] = await Promise.all([
            fetch('/api/repositories/analysis/cached').then(r => r.json()).catch(() => ({})),
            fetch('/api/repositories/report/cached').then(r => r.json()).catch(() => ({}))
        ]);

        const reposSet = new Set();
        (archRes.repositories || []).forEach(r => {
            const name = r.full_name || (r.owner && r.name ? `${r.owner}/${r.name}` : null);
            if (name) reposSet.add(name);
        });
        (repRes.reports || []).forEach(r => {
            if (r.full_name) reposSet.add(r.full_name);
        });

        // Ensure key sample repos are present
        ['psf/requests', 'bottlepy/bottle', 'pallets/flask', 'fastapi/fastapi'].forEach(r => reposSet.add(r));

        select.innerHTML = '<option value="">-- Choose Analyzed Repository --</option>';
        Array.from(reposSet).sort().forEach(r => {
            const opt = document.createElement('option');
            opt.value = r;
            opt.textContent = r;
            select.appendChild(opt);
        });
    } catch (err) {
        console.error('[CodeLens AI] Error populating chat repo dropdown:', err);
    }
}

/**
 * Set active repository for chat assistant and update links and suggested questions.
 * @param {string} repoName
 */
function selectChatRepo(repoName) {
    if (!repoName) return;
    currentChatRepo = repoName.trim();

    try {
        localStorage.setItem('codelens_last_repo', currentChatRepo);
    } catch (e) {}
    syncNavigationRepoParams(currentChatRepo);

    const emptyEl = document.getElementById('chat-empty-state');
    if (emptyEl) emptyEl.style.display = 'none';
    const streamCard = document.querySelector('.chat-stream-card');
    if (streamCard) streamCard.style.display = 'block';
    const suggestSection = document.querySelector('.chat-suggested-section');
    if (suggestSection) suggestSection.style.display = 'block';
    const reportCta = document.getElementById('chat-report-cta');
    if (reportCta) reportCta.style.display = 'flex';

    const select = document.getElementById('chat-repo-select');
    if (select) select.value = currentChatRepo;

    const activeLabel = document.getElementById('chat-active-repo-label');
    if (activeLabel) activeLabel.textContent = currentChatRepo;

    // Update secondary header links and Cross-Feature CTA
    const repoParam = encodeURIComponent(currentChatRepo);
    const btnArch = document.getElementById('btn-chat-arch');
    const btnReport = document.getElementById('btn-chat-report');
    const btnReportCta = document.getElementById('btn-chat-report-cta');
    const btnAnalysis = document.getElementById('btn-chat-analysis');

    if (btnArch) btnArch.href = `/architecture?repo=${repoParam}`;
    if (btnReport) btnReport.href = `/report?repo=${repoParam}`;
    if (btnReportCta) btnReportCta.href = `/report?repo=${repoParam}`;
    if (btnAnalysis) btnAnalysis.href = `/analysis?repo=${repoParam}`;

    // Update URL smoothly
    const newUrl = `${window.location.pathname}?repo=${repoParam}`;
    window.history.pushState({ path: newUrl }, '', newUrl);

    // Refresh suggested questions for this repo
    loadSuggestedQuestions(currentChatRepo);
}

/**
 * Handle repository change from the chat dropdown with strict repository isolation.
 * @param {string} repoName
 */
function onChatRepoSelected(repoName) {
    if (!repoName) return;
    // When switching repo, reset session ID for complete repo isolation
    currentChatSessionId = generateSessionId();
    selectChatRepo(repoName);

    // Add a system notice message in chat log
    appendSystemNoticeMessage(`Switched context to repository: **${repoName}**. Conversational context has been isolated.`);
}

/**
 * Load tailored suggested questions for the selected repository.
 * @param {string} repo
 */
async function loadSuggestedQuestions(repo) {
    const chipsContainer = document.getElementById('chat-suggested-chips');
    if (!chipsContainer || !repo) return;

    try {
        const resp = await fetch(`/api/chat/suggested?repo=${encodeURIComponent(repo)}`);
        const data = await resp.json();
        if (data.success && data.questions && data.questions.length > 0) {
            chipsContainer.innerHTML = data.questions.map(q => `
                <button class="chat-suggest-pill" onclick="askSuggestedQuestion('${escapeHtml(q.text)}')">
                    ${q.icon || '💬'} ${escapeHtml(q.text)}
                </button>
            `).join('');
        }
    } catch (e) {
        console.warn('Could not load customized suggested questions:', e);
    }
}

/**
 * Check active LLM status.
 */
async function checkLlmStatus() {
    const badge = document.getElementById('chat-llm-badge');
    if (!badge) return;

    try {
        const resp = await fetch('/api/chat/status');
        const data = await resp.json();
        if (data.success && data.is_configured) {
            badge.textContent = `LLM: ${data.model} (${data.provider})`;
            badge.className = 'badge badge-success';
        } else {
            badge.textContent = 'LLM: Grounded Fallback Mode';
            badge.className = 'badge badge-warning';
            badge.title = 'GROQ_API_KEY is not configured. Real-time deterministic analysis fallback active.';
        }
    } catch (e) {
        badge.textContent = 'LLM: Standby';
    }
}

/**
 * Populate input and immediately submit suggested question.
 * @param {string} text
 */
function askSuggestedQuestion(text) {
    const input = document.getElementById('chat-user-input');
    if (input) {
        input.value = text;
        submitChatMessage();
    }
}

/**
 * Submit chat on Enter key (Shift+Enter for newline).
 * @param {KeyboardEvent} event
 */
function onChatInputKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        submitChatMessage();
    }
}

/**
 * Submit user question to the backend chat API.
 */
async function submitChatMessage() {
    const input = document.getElementById('chat-user-input');
    const sendBtn = document.getElementById('btn-chat-send');
    const typingIndicator = document.getElementById('chat-typing-indicator');
    const container = document.getElementById('chat-messages-container');

    if (!input || !currentChatRepo) return;
    const text = input.value.trim();
    if (!text) return;

    // Clear input
    input.value = '';

    // 1. Append User Message Bubble
    appendUserMessage(text);

    // Disable send button & show typing indicator
    if (sendBtn) sendBtn.disabled = true;
    if (typingIndicator) typingIndicator.style.display = 'flex';
    container.scrollTop = container.scrollHeight;

    try {
        const resp = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                repo: currentChatRepo,
                message: text,
                question: text,
                session_id: currentChatSessionId,
            })
        });

        const res = await resp.json();
        const data = res.data || res;

        if (resp.ok && (data.success || data.answer)) {
            appendAssistantMessage(data.answer, data.sources || []);
        } else {
            const errMsg = data.error || data.message || 'Could not process question.';
            appendAssistantMessage(`⚠️ **Unable to answer:** ${errMsg}`);
        }
    } catch (err) {
        console.error('[CodeLens AI] Chat submit error:', err);
        appendAssistantMessage(`⚠️ **Connection Error:** Could not reach the AI service (${err.message || 'Network error'}). Please try again.`);
    } finally {
        if (sendBtn) sendBtn.disabled = false;
        if (typingIndicator) typingIndicator.style.display = 'none';
        container.scrollTop = container.scrollHeight;
        input.focus();
    }
}

/**
 * Append user message bubble to chat container.
 * @param {string} text
 */
function appendUserMessage(text) {
    const container = document.getElementById('chat-messages-container');
    if (!container) return;

    const msgEl = document.createElement('div');
    msgEl.className = 'chat-message user-message';
    msgEl.innerHTML = `
        <div class="chat-bubble user-bubble">
            <p>${escapeHtml(text)}</p>
        </div>
        <div class="chat-avatar user-avatar" title="You">
            <img src="/static/images/user-avatar.svg" width="16" height="16" alt="" class="chat-avatar-icon" aria-hidden="true" />
        </div>
    `;
    container.appendChild(msgEl);
    container.scrollTop = container.scrollHeight;
}

/**
 * Append assistant response bubble with markdown rendering and source citations.
 * @param {string} answerText
 * @param {Array} sources
 */
function appendAssistantMessage(answerText, sources = []) {
    const container = document.getElementById('chat-messages-container');
    if (!container) return;

    const formattedAnswer = formatMarkdownResponse(answerText);

    let sourcesHtml = '';
    if (sources && sources.length > 0) {
        sourcesHtml = `
            <div class="chat-sources-block">
                <div class="chat-sources-title">
                    <img src="/static/images/sources-icon.svg" width="12" height="12" alt="" class="chat-sources-icon" aria-hidden="true" />
                    <span>Grounded Sources Used:</span>
                </div>
                <div class="chat-sources-list">
                    ${sources.map(s => {
                        const icon = s.type === 'file' ? '📄' : (s.type === 'class' ? '🅲' : (s.type === 'function' ? '🅵' : (s.type === 'readme' ? '📖' : '📦')));
                        return `<span class="chat-source-chip" title="${escapeHtml(s.detail || s.path || s.name)}">${icon} ${escapeHtml(s.name)}</span>`;
                    }).join('')}
                </div>
            </div>
        `;
    }

    const msgEl = document.createElement('div');
    msgEl.className = 'chat-message assistant-message';
    msgEl.innerHTML = `
        <div class="chat-avatar assistant-avatar" title="CodeLens AI Assistant">
            <img src="/static/images/assistant-avatar.svg" width="18" height="18" alt="" class="chat-avatar-icon" aria-hidden="true" />
        </div>
        <div class="chat-bubble assistant-bubble">
            <div class="chat-sender-title">CodeLens AI Comprehension Assistant</div>
            <div class="chat-text-content">
                ${formattedAnswer}
            </div>
            ${sourcesHtml}
        </div>
    `;
    container.appendChild(msgEl);
    container.scrollTop = container.scrollHeight;
}

/**
 * Append system notice message into chat log.
 * @param {string} text
 */
function appendSystemNoticeMessage(text) {
    const container = document.getElementById('chat-messages-container');
    if (!container) return;

    const msgEl = document.createElement('div');
    msgEl.style.textAlign = 'center';
    msgEl.style.margin = '0.5rem 0';
    msgEl.style.fontSize = '0.78rem';
    msgEl.style.color = 'var(--text-muted)';
    msgEl.innerHTML = `<em>${formatMarkdownResponse(text)}</em>`;
    container.appendChild(msgEl);
    container.scrollTop = container.scrollHeight;
}

/**
 * Parse markdown into clean HTML.
 * @param {string} text
 * @returns {string}
 */
function formatMarkdownResponse(text) {
    if (!text) return '';
    let html = escapeHtml(text).replace(/\\n/g, '\n');

    // Code blocks ```...```
    html = html.replace(/```([a-zA-Z0-9_]*)\n([\s\S]*?)```/g, (match, lang, code) => {
        return `<pre><code>${code.trim()}</code></pre>`;
    });

    // Inline code `...`
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Bold **...**
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // Italic *...*
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');

    // Alert Callouts > [!NOTE]
    html = html.replace(/&gt; \[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\n([\s\S]*?)(?=\n\n|$)/g, (m, type, body) => {
        const cleaned = body.replace(/&gt; ?/g, '').trim().replace(/\n/g, '<br/>');
        return `<div class="chat-alert-box chat-alert-${type.toLowerCase()}" style="display:block; padding:0.75rem 1rem; margin-bottom:0.85rem; border-radius:6px; font-size:0.82rem; line-height:1.5; background:rgba(37,99,235,0.08); border-left:4px solid #2563eb; color:var(--text-primary); text-align:left;">${cleaned}</div>`;
    });

    // Blockquotes > ...
    html = html.replace(/(?:^|\n)&gt; (.*?)(?=\n\n|$)/g, (match, quote) => {
        return `<blockquote style="margin:0.6rem 0; padding:0.5rem 0.85rem; border-left:3px solid var(--primary-color, #2563eb); background:rgba(255,255,255,0.03); font-style:italic; border-radius:0 4px 4px 0;">${quote}</blockquote>`;
    });

    // Headers ### ...
    html = html.replace(/^### (.*$)/gim, '<h4 style="margin:0.75rem 0 0.35rem 0; font-size:1rem; color:var(--text-primary);">$1</h4>');
    html = html.replace(/^## (.*$)/gim, '<h3 style="margin:0.85rem 0 0.4rem 0; font-size:1.1rem; color:var(--text-primary);">$1</h3>');

    // Bullet points & numbered lists
    html = html.replace(/^\s*-\s+(.*$)/gim, '<li>$1</li>');
    html = html.replace(/^\s*\d+\.\s+(.*$)/gim, '<li>$1</li>');
    html = html.replace(/(<li>(?:(?!<ul)[\s\S])*?<\/li>)/gms, '<ul>$1</ul>');
    html = html.replace(/<\/ul>\s*<ul>/g, '');

    // Paragraph line breaks
    const paragraphs = html.split(/\n{2,}/);
    return paragraphs.map(p => {
        p = p.trim();
        if (p.startsWith('<h') || p.startsWith('<pre') || p.startsWith('<ul>') || p.startsWith('<div') || p.startsWith('<blockquote')) {
            return p;
        }
        return `<p>${p.replace(/\n/g, '<br/>')}</p>`;
    }).join('');
}

/**
 * Clear conversational history.
 */
async function clearCurrentChat() {
    if (currentChatSessionId) {
        try {
            await fetch('/api/chat/clear', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: currentChatSessionId })
            });
        } catch (e) {}
    }

    currentChatSessionId = generateSessionId();
    const container = document.getElementById('chat-messages-container');
    if (container) {
        container.innerHTML = `
            <div class="chat-message assistant-message">
                <div class="chat-avatar assistant-avatar" title="CodeLens AI Assistant">
                    <img src="/static/images/assistant-avatar.svg" width="18" height="18" alt="" class="chat-avatar-icon" aria-hidden="true" />
                </div>
                <div class="chat-bubble assistant-bubble">
                    <div class="chat-sender-title">CodeLens AI Comprehension Assistant</div>
                    <div class="chat-text-content">
                        <p>Understand this project with AI. Ask me anything about the selected repository. I can explain what the project does, how its parts work together, and help you understand the code step by step.</p>
                        <p style="margin-top: 0.5rem; margin-bottom: 0; font-size: 0.825rem; color: var(--text-muted);">
                            <em>Select an inquiry from the suggestions above or type any question below.</em>
                        </p>
                    </div>
                </div>
            </div>
        `;
    }

    showToast('Chat Cleared', 'Conversational history has been reset.', 'info');
}


