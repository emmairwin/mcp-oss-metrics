import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv
from mcp.server import Server
from mcp.types import Tool, TextContent
from textblob import TextBlob

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("project-risk-analyzer")

@dataclass
class RiskAnalysis:
    """Structure for risk analysis results"""
    repository: str
    overall_risk_score: float  # 0-1, higher is more risky
    risk_factors: Dict[str, Any]
    recommendations: List[str]
    analysis_date: str

class ProjectRiskAnalyzer:
    """Core logic for analyzing project maintainer/contributor risks"""
    
    def __init__(self, custom_domains=None):
        self.github_token = os.getenv("GITHUB_TOKEN")  # Load from environment
        self.github_api_url = os.getenv("GITHUB_API_URL", "https://api.github.com")
        self.analysis_window_days = 365  # Default to last year
        self.custom_domains = custom_domains or []  # User-provided company domains
        
        # Define email domain categories
        self.company_domains = {
            "microsoft.com", "google.com", "facebook.com", "meta.com", "apple.com", 
            "amazon.com", "netflix.com", "uber.com", "airbnb.com", "twitter.com",
            "linkedin.com", "github.com", "gitlab.com", "atlassian.com", "salesforce.com",
            "oracle.com", "ibm.com", "intel.com", "nvidia.com", "amd.com", "cisco.com",
            "vmware.com", "redhat.com", "canonical.com", "mozilla.org", "spotify.com",
            "dropbox.com", "slack.com", "zoom.us", "docker.com", "hashicorp.com"
        }
        
        self.personal_domains = {
            "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com",
            "icloud.com", "protonmail.com", "mail.com", "yandex.com", "qq.com",
            "163.com", "126.com", "sina.com", "sohu.com", "naver.com", "daum.net",
            "web.de", "gmx.de", "t-online.de", "free.fr", "laposte.net"
        }
        
        self.academic_tlds = {".edu", ".ac.uk", ".edu.au", ".ac.jp", ".edu.cn"}
        
        if not self.github_token:
            logger.warning("No GITHUB_TOKEN found in environment. API calls will be rate-limited.")
        else:
            logger.info("GitHub token loaded successfully.")
    
    def _classify_email_domain(self, email: str) -> str:
        """Classify email domain as company, personal, academic, custom, or personal (default)"""
        if not email or "@" not in email:
            return "no email available"
        
        domain = email.split("@")[-1].lower()
        
        # Check custom domains first
        if domain in self.custom_domains:
            return "custom"
        
        # Check company domains
        if domain in self.company_domains:
            return "company"
        
        # Check academic domains
        for tld in self.academic_tlds:
            if domain.endswith(tld):
                return "academic"
        
        # Check well-known personal domains
        if domain in self.personal_domains:
            return "personal"
        
        # Default to personal for any other email (like dev@modprog.de)
        return "personal"
    
    def _is_bot_account(self, login: str, name: str, email: str) -> bool:
        """Detect if an account is likely a bot"""
        if not login:
            return False
        
        login_lower = login.lower()
        name_lower = name.lower() if name else ""
        
        # Common bot indicators in usernames
        bot_indicators = [
            "bot", "automated", "auto", "ci", "cd", "deploy", "build", 
            "github-actions", "dependabot", "renovate", "greenkeeper",
            "codecov", "codeclimate", "travis", "appveyor", "jenkins",
            "drone", "circleci", "gitlab-ci", "azure-devops", "teamcity",
            "service", "automation", "pipeline", "workflow", "action"
        ]
        
        # Check username
        for indicator in bot_indicators:
            if indicator in login_lower:
                return True
        
        # Check display name
        for indicator in bot_indicators:
            if indicator in name_lower:
                return True
        
        # Common bot email patterns
        if email:
            email_lower = email.lower()
            bot_email_patterns = [
                "noreply", "no-reply", "automation", "bot", "ci", "cd",
                "github-actions", "dependabot", "renovate"
            ]
            for pattern in bot_email_patterns:
                if pattern in email_lower:
                    return True
        
        # GitHub's bot account pattern (ends with [bot])
        if login_lower.endswith("[bot]") or name_lower.endswith("[bot]"):
            return True
        
        return False
    
    def _analyze_sentiment(self, text: str) -> Dict[str, float]:
        """Analyze sentiment of text using TextBlob"""
        if not text or not text.strip():
            return {"polarity": 0.0, "subjectivity": 0.0}
        
        try:
            # Remove the type prefix (COMMIT:, PR_REVIEW:, etc.) for sentiment analysis
            if ":" in text:
                text = text.split(":", 1)[1].strip()
            
            blob = TextBlob(text)
            return {
                "polarity": blob.sentiment.polarity,  # -1 (negative) to 1 (positive)
                "subjectivity": blob.sentiment.subjectivity  # 0 (objective) to 1 (subjective)
            }
        except Exception as e:
            return {"polarity": 0.0, "subjectivity": 0.0}
    
    async def _fetch_contributor_comments(self, owner: str, repo: str, contributor_login: str) -> List[str]:
        """Fetch all types of comments/messages made by a specific contributor within the analysis timeframe"""
        comments = []
        
        if not self.github_token:
            return comments
        
        headers = {"Authorization": f"token {self.github_token}"}
        
        # Calculate the same timeframe as our main analysis
        now = datetime.now()
        cutoff_date = now - timedelta(days=self.analysis_window_days)
        
        try:
            async with httpx.AsyncClient() as client:
                # 1. Get commit messages from this contributor
                commits_url = f"{self.github_api_url}/repos/{owner}/{repo}/commits"
                params = {"author": contributor_login, "per_page": 50, "since": cutoff_date.isoformat()}
                
                try:
                    response = await client.get(commits_url, headers=headers, params=params)
                    if response.status_code == 200:
                        commits = response.json()
                        for commit in commits:
                            commit_message = commit.get("commit", {}).get("message", "")
                            if commit_message and commit_message.strip():
                                # Clean up commit message (remove merge commit noise)
                                lines = commit_message.split('\n')
                                first_line = lines[0].strip()
                                if first_line and not first_line.startswith("Merge "):
                                    comments.append(f"COMMIT: {first_line}")
                except Exception as e:
                    pass
                
                # 2. Get issue and PR comments
                issues_url = f"{self.github_api_url}/repos/{owner}/{repo}/issues"
                params = {"state": "all", "per_page": 100, "sort": "updated", "direction": "desc"}
                
                try:
                    response = await client.get(issues_url, headers=headers, params=params)
                    if response.status_code == 200:
                        issues = response.json()
                        
                        for issue in issues:
                            # Check if this issue/PR has comments from our contributor
                            if issue.get("comments", 0) > 0:
                                comments_url = issue.get("comments_url", "")
                                if comments_url:
                                    comment_response = await client.get(comments_url, headers=headers)
                                    if comment_response.status_code == 200:
                                        issue_comments = comment_response.json()
                                        
                                        # Filter comments by our contributor AND timeframe
                                        for comment in issue_comments:
                                            comment_user = comment.get("user", {})
                                            if comment_user.get("login") == contributor_login:
                                                # Check comment date is within our analysis window
                                                comment_date_str = comment.get("created_at", "")
                                                if comment_date_str:
                                                    try:
                                                        # Handle GitHub's ISO format with Z timezone
                                                        if comment_date_str.endswith('Z'):
                                                            comment_date_str = comment_date_str[:-1] + '+00:00'
                                                        comment_date = datetime.fromisoformat(comment_date_str)
                                                        # Convert to naive datetime for comparison
                                                        if comment_date.tzinfo is not None:
                                                            comment_date = comment_date.replace(tzinfo=None)
                                                        
                                                        # Only include comments within our analysis window
                                                        if comment_date >= cutoff_date:
                                                            comment_body = comment.get("body", "")
                                                            if comment_body and comment_body.strip():
                                                                issue_type = "PR" if issue.get("pull_request") else "ISSUE"
                                                                comments.append(f"{issue_type}_COMMENT: {comment_body}")
                                                    except Exception as e:
                                                        pass
                            
                            # 3. Get PR review comments if this is a PR
                            if issue.get("pull_request"):
                                pr_number = issue.get("number")
                                reviews_url = f"{self.github_api_url}/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
                                
                                try:
                                    review_response = await client.get(reviews_url, headers=headers)
                                    if review_response.status_code == 200:
                                        reviews = review_response.json()
                                        
                                        for review in reviews:
                                            review_user = review.get("user", {})
                                            if review_user.get("login") == contributor_login:
                                                # Check review date
                                                review_date_str = review.get("submitted_at", "")
                                                if review_date_str:
                                                    try:
                                                        if review_date_str.endswith('Z'):
                                                            review_date_str = review_date_str[:-1] + '+00:00'
                                                        review_date = datetime.fromisoformat(review_date_str)
                                                        if review_date.tzinfo is not None:
                                                            review_date = review_date.replace(tzinfo=None)
                                                        
                                                        if review_date >= cutoff_date:
                                                            review_body = review.get("body", "")
                                                            if review_body and review_body.strip():
                                                                comments.append(f"PR_REVIEW: {review_body}")
                                                    except Exception as e:
                                                        pass
                                except Exception as e:
                                    pass
                                
                                # 4. Get PR review comments (line-by-line comments)
                                review_comments_url = f"{self.github_api_url}/repos/{owner}/{repo}/pulls/{pr_number}/comments"
                                
                                try:
                                    review_comment_response = await client.get(review_comments_url, headers=headers)
                                    if review_comment_response.status_code == 200:
                                        review_comments = review_comment_response.json()
                                        
                                        for review_comment in review_comments:
                                            comment_user = review_comment.get("user", {})
                                            if comment_user.get("login") == contributor_login:
                                                comment_date_str = review_comment.get("created_at", "")
                                                if comment_date_str:
                                                    try:
                                                        if comment_date_str.endswith('Z'):
                                                            comment_date_str = comment_date_str[:-1] + '+00:00'
                                                        comment_date = datetime.fromisoformat(comment_date_str)
                                                        if comment_date.tzinfo is not None:
                                                            comment_date = comment_date.replace(tzinfo=None)
                                                        
                                                        if comment_date >= cutoff_date:
                                                            comment_body = review_comment.get("body", "")
                                                            if comment_body and comment_body.strip():
                                                                comments.append(f"PR_LINE_COMMENT: {comment_body}")
                                                    except Exception as e:
                                                        pass
                                except Exception as e:
                                    pass
                except Exception as e:
                    pass
                
        except Exception as e:
            pass
        
        return comments[:30]  # Increase limit since we're getting more comprehensive data
        
    async def _analyze_contributor_sentiment(self, owner: str, repo: str, contributors: Dict[str, Any]) -> None:
        """Add sentiment analysis to contributor data"""
        # Count contributors eligible for sentiment analysis
        eligible_contributors = [login for login, data in contributors.items() if data["total_activity"] >= 10]
        # Analyze sentiment for contributors with 10+ activities
        
        for login, contributor_data in contributors.items():
            if contributor_data["total_activity"] >= 10:  # Only analyze sentiment for highly active contributors
                comments = await self._fetch_contributor_comments(owner, repo, login)
                
                if comments:
                    # Analyze sentiment of all comments
                    sentiments = [self._analyze_sentiment(comment) for comment in comments]
                    
                    # Calculate average sentiment
                    if sentiments:
                        avg_polarity = sum(s["polarity"] for s in sentiments) / len(sentiments)
                        avg_subjectivity = sum(s["subjectivity"] for s in sentiments) / len(sentiments)
                        
                        contributor_data["sentiment_analysis"] = {
                            "average_polarity": round(avg_polarity, 3),
                            "average_subjectivity": round(avg_subjectivity, 3),
                            "comments_analyzed": len(comments),
                            "sentiment_label": self._get_sentiment_label(avg_polarity)
                        }
                    else:
                        contributor_data["sentiment_analysis"] = {
                            "average_polarity": 0.0,
                            "average_subjectivity": 0.0,
                            "comments_analyzed": 0,
                            "sentiment_label": "neutral"
                        }
                else:
                    # More accurate label - we didn't find comments in our sample, not that they never comment
                    contributor_data["sentiment_analysis"] = {
                        "average_polarity": 0.0,
                        "average_subjectivity": 0.0,
                        "comments_analyzed": 0,
                        "sentiment_label": "no_recent_comments_found"
                    }
            else:
                contributor_data["sentiment_analysis"] = {
                    "average_polarity": 0.0,
                    "average_subjectivity": 0.0,
                    "comments_analyzed": 0,
                    "sentiment_label": "insufficient_activity"
                }
    
    def _get_sentiment_label(self, polarity: float) -> str:
        """Convert polarity score to human-readable label"""
        if polarity > 0.3:
            return "positive"
        elif polarity < -0.3:
            return "negative"
        else:
            return "neutral"
    
    def _calculate_repository_statistics(self, issues: List[Dict], commits: List[Dict]) -> Dict[str, Any]:
        """Calculate overall repository statistics for the analysis period"""
        stats = {
            "total_issues": 0,
            "total_prs": 0,
            "closed_issues": 0,
            "closed_prs": 0,
            "avg_issue_close_time_days": None,
            "avg_pr_close_time_days": None,
            "avg_response_time_days": None,
            "total_commits": len(commits),
            "commit_frequency_per_day": 0
        }
        
        if not issues:
            return stats
        
        issue_close_times = []
        pr_close_times = []
        response_times = []
        
        for issue in issues:
            if not issue or not isinstance(issue, dict):
                continue
            
            created_at_str = issue.get("created_at", "")
            closed_at_str = issue.get("closed_at")
            
            if not created_at_str:
                continue
            
            try:
                # Parse creation date
                if created_at_str.endswith('Z'):
                    created_at_str = created_at_str[:-1] + '+00:00'
                created_at = datetime.fromisoformat(created_at_str)
                if created_at.tzinfo is not None:
                    created_at = created_at.replace(tzinfo=None)
                
                is_pr = bool(issue.get("pull_request"))
                
                if is_pr:
                    stats["total_prs"] += 1
                else:
                    stats["total_issues"] += 1
                
                # Calculate close time if closed
                if closed_at_str:
                    try:
                        if closed_at_str.endswith('Z'):
                            closed_at_str = closed_at_str[:-1] + '+00:00'
                        closed_at = datetime.fromisoformat(closed_at_str)
                        if closed_at.tzinfo is not None:
                            closed_at = closed_at.replace(tzinfo=None)
                        
                        close_time_days = (closed_at - created_at).total_seconds() / (24 * 3600)
                        
                        if is_pr:
                            stats["closed_prs"] += 1
                            pr_close_times.append(close_time_days)
                        else:
                            stats["closed_issues"] += 1
                            issue_close_times.append(close_time_days)
                        
                        # Calculate response time (time to first close - simplified)
                        response_time_days = (closed_at - created_at).total_seconds() / (24 * 3600)
                        response_times.append(response_time_days)
                    except Exception:
                        # Skip if we can't parse the closed date
                        continue
                
            except Exception as e:
                # Skip issues with parsing errors
                continue
        
        # Calculate averages
        if issue_close_times:
            stats["avg_issue_close_time_days"] = round(sum(issue_close_times) / len(issue_close_times), 2)
        
        if pr_close_times:
            stats["avg_pr_close_time_days"] = round(sum(pr_close_times) / len(pr_close_times), 2)
        
        if response_times:
            stats["avg_response_time_days"] = round(sum(response_times) / len(response_times), 2)
        
        # Calculate commit frequency (commits per day over analysis window)
        if self.analysis_window_days > 0:
            stats["commit_frequency_per_day"] = round(len(commits) / self.analysis_window_days, 2)
        
        return stats
        
    async def analyze_repositories(self, repo_urls: List[str]) -> List[RiskAnalysis]:
        """Main entry point for analyzing multiple repositories"""
        analyses = []
        
        for repo_url in repo_urls:
            try:
                analysis = await self.analyze_single_repository(repo_url)
                analyses.append(analysis)
            except Exception as e:
                logger.error(f"Failed to analyze {repo_url}: {e}")
                # Return error analysis
                analyses.append(RiskAnalysis(
                    repository=repo_url,
                    overall_risk_score=1.0,  # Max risk for failed analysis
                    risk_factors={"error": str(e)},
                    recommendations=["Unable to analyze repository"],
                    analysis_date=datetime.now().isoformat()
                ))
        
        return analyses
    
    async def analyze_single_repository(self, repo_url: str) -> RiskAnalysis:
        """Analyze a single repository for maintainer/contributor risks"""
        
        logger.info(f"Analyzing repository: {repo_url}")
        
        # Extract owner/repo from URL
        owner, repo = self._parse_github_url(repo_url)
        
        # Fetch repository data
        repo_data = await self._fetch_repository_data(owner, repo)
        commits_data = await self._fetch_commits_data(owner, repo)
        contributors_data = await self._fetch_contributors_data(owner, repo)
        issues_data = await self._fetch_issues_data(owner, repo)
        
        # Perform risk analysis
        risk_factors = {}
        
        # 1. Contributor concentration analysis
        contributor_risk = await self._analyze_contributor_concentration(owner, repo, commits_data, contributors_data, issues_data)
        risk_factors.update(contributor_risk)
        
        # Calculate overall risk score (based only on contributor concentration for now)
        overall_risk = contributor_risk.get("contributor_concentration_risk", 0.5)
        
        # Generate recommendations
        recommendations = self._generate_recommendations(risk_factors)
        
        logger.info(f"Analysis complete for {repo_url}")
        
        return RiskAnalysis(
            repository=repo_url,
            overall_risk_score=overall_risk,
            risk_factors=risk_factors,
            recommendations=recommendations,
            analysis_date=datetime.now().isoformat()
        )
    
    def _parse_github_url(self, repo_url: str) -> tuple[str, str]:
        """Extract owner and repo name from GitHub URL"""
        # TODO: Implement URL parsing
        # Handle formats like:
        # - https://github.com/owner/repo
        # - https://github.com/owner/repo.git
        # - owner/repo
        
        # Stub implementation
        if 'github.com' in repo_url:
            parts = repo_url.strip('/').split('/')
            return parts[-2], parts[-1].replace('.git', '')
        else:
            # Assume format is owner/repo
            owner, repo = repo_url.split('/')
            return owner, repo
    
    def _filter_recent_commits(self, commits: List[Dict]) -> List[Dict]:
        """Filter commits to only include those within the analysis window"""
        now = datetime.now()
        cutoff_date = now - timedelta(days=self.analysis_window_days)
        
        recent_commits = []
        for commit in commits:
            commit_date_str = commit.get("commit", {}).get("author", {}).get("date", "")
            if commit_date_str:
                try:
                    # Handle GitHub's ISO format with Z timezone
                    if commit_date_str.endswith('Z'):
                        commit_date_str = commit_date_str[:-1] + '+00:00'
                    commit_date = datetime.fromisoformat(commit_date_str)
                    # Convert to naive datetime for comparison
                    if commit_date.tzinfo is not None:
                        commit_date = commit_date.replace(tzinfo=None)
                    
                    if commit_date >= cutoff_date:
                        recent_commits.append(commit)
                except Exception as e:
                    pass
        
        return recent_commits
    
    def _filter_recent_issues(self, issues: List[Dict]) -> List[Dict]:
        """Filter issues to only include those within the analysis window"""
        now = datetime.now()
        cutoff_date = now - timedelta(days=self.analysis_window_days)
        
        recent_issues = []
        for issue in issues:
            created_at_str = issue.get("created_at", "")
            if created_at_str:
                try:
                    # Handle GitHub's ISO format with Z timezone
                    if created_at_str.endswith('Z'):
                        created_at_str = created_at_str[:-1] + '+00:00'
                    created_at = datetime.fromisoformat(created_at_str)
                    # Convert to naive datetime for comparison
                    if created_at.tzinfo is not None:
                        created_at = created_at.replace(tzinfo=None)
                    
                    if created_at >= cutoff_date:
                        recent_issues.append(issue)
                except:
                    pass
        return recent_issues
    
    async def _fetch_repository_data(self, owner: str, repo: str) -> Dict[str, Any]:
        """Fetch basic repository information from GitHub API"""
        url = f"{self.github_api_url}/repos/{owner}/{repo}"
        headers = {}
        if self.github_token:
            headers["Authorization"] = f"token {self.github_token}"
        headers["Accept"] = "application/vnd.github.v3+json"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error fetching repository data for {owner}/{repo}: {e}")
                # Return minimal stub data on error
                return {
                    "name": repo,
                    "full_name": f"{owner}/{repo}",
                    "created_at": "2020-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z",
                    "stargazers_count": 0,
                    "forks_count": 0,
                    "open_issues_count": 0
                }
            except Exception as e:
                logger.error(f"Error fetching repository data for {owner}/{repo}: {e}")
                raise
    
    async def _fetch_commits_data(self, owner: str, repo: str) -> List[Dict[str, Any]]:
        """Fetch recent commits data from GitHub API"""
        url = f"{self.github_api_url}/repos/{owner}/{repo}/commits"
        headers = {}
        if self.github_token:
            headers["Authorization"] = f"token {self.github_token}"
        headers["Accept"] = "application/vnd.github.v3+json"
        
        # Get commits from the last year only
        since_date = (datetime.now() - timedelta(days=self.analysis_window_days)).isoformat()
        params = {
            "since": since_date,
            "per_page": 100  # Get up to 100 commits per page
        }
        
        all_commits = []
        page = 1
        
        async with httpx.AsyncClient() as client:
            try:
                while len(all_commits) < 500:  # Limit to 500 commits max to avoid rate limits
                    params["page"] = page
                    response = await client.get(url, headers=headers, params=params)
                    response.raise_for_status()
                    
                    commits = response.json()
                    if not commits:  # No more commits
                        break
                    
                    all_commits.extend(commits)
                    
                    # Check if we have more pages
                    if len(commits) < params["per_page"]:
                        break
                    
                    page += 1
                
                logger.info(f"Fetched {len(all_commits)} commits for {owner}/{repo}")
                return all_commits
                
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error fetching commits for {owner}/{repo}: {e}")
                # Return empty list on error
                return []
            except Exception as e:
                logger.error(f"Error fetching commits for {owner}/{repo}: {e}")
                raise
    
    async def _fetch_contributors_data(self, owner: str, repo: str) -> List[Dict[str, Any]]:
        """Fetch contributors statistics from GitHub API"""
        url = f"{self.github_api_url}/repos/{owner}/{repo}/contributors"
        headers = {}
        if self.github_token:
            headers["Authorization"] = f"token {self.github_token}"
        headers["Accept"] = "application/vnd.github.v3+json"
        
        params = {"per_page": 100}
        all_contributors = []
        page = 1
        
        async with httpx.AsyncClient() as client:
            try:
                while len(all_contributors) < 200:  # Limit to 200 contributors
                    params["page"] = page
                    response = await client.get(url, headers=headers, params=params)
                    response.raise_for_status()
                    
                    contributors = response.json()
                    if not contributors:
                        break
                    
                    all_contributors.extend(contributors)
                    
                    if len(contributors) < params["per_page"]:
                        break
                    
                    page += 1
                
                logger.info(f"Fetched {len(all_contributors)} contributors for {owner}/{repo}")
                return all_contributors
                
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error fetching contributors for {owner}/{repo}: {e}")
                return []
            except Exception as e:
                logger.error(f"Error fetching contributors for {owner}/{repo}: {e}")
                raise
    
    async def _fetch_issues_data(self, owner: str, repo: str) -> List[Dict[str, Any]]:
        """Fetch recent issues and PRs data from GitHub API"""
        headers = {}
        if self.github_token:
            headers["Authorization"] = f"token {self.github_token}"
        headers["Accept"] = "application/vnd.github.v3+json"
        
        # Get issues from the last year
        since_date = (datetime.now() - timedelta(days=self.analysis_window_days)).isoformat()
        params = {
            "state": "all",  # Get both open and closed
            "since": since_date,
            "per_page": 100
        }
        
        all_issues = []
        
        async with httpx.AsyncClient() as client:
            try:
                # Fetch issues (includes PRs in GitHub API)
                issues_url = f"{self.github_api_url}/repos/{owner}/{repo}/issues"
                page = 1
                
                while len(all_issues) < 200:  # Limit to 200 issues/PRs
                    params["page"] = page
                    response = await client.get(issues_url, headers=headers, params=params)
                    response.raise_for_status()
                    
                    issues = response.json()
                    if not issues:
                        break
                    
                    # For each PR, get additional review data
                    for issue in issues:
                        if issue.get("pull_request"):
                            # This is a PR, fetch review data
                            try:
                                pr_number = issue["number"]
                                reviews_url = f"{self.github_api_url}/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
                                reviews_response = await client.get(reviews_url, headers=headers)
                                if reviews_response.status_code == 200:
                                    issue["reviews"] = reviews_response.json()
                                else:
                                    issue["reviews"] = []
                                
                                # Get participants (rough approximation from timeline)
                                timeline_url = f"{self.github_api_url}/repos/{owner}/{repo}/issues/{pr_number}/timeline"
                                timeline_headers = headers.copy()
                                timeline_headers["Accept"] = "application/vnd.github.v3.timeline+json"
                                timeline_response = await client.get(timeline_url, headers=timeline_headers)
                                
                                participants = set()
                                if timeline_response.status_code == 200:
                                    timeline = timeline_response.json()
                                    for event in timeline:
                                        if event.get("actor", {}).get("login"):
                                            participants.add(event["actor"]["login"])
                                
                                issue["participants"] = list(participants)
                            except Exception as e:
                                logger.warning(f"Could not fetch PR details for #{pr_number}: {e}")
                                issue["reviews"] = []
                                issue["participants"] = []
                        else:
                            # For regular issues, approximate participants from comments
                            participants = {issue["user"]["login"]}
                            if issue.get("assignees"):
                                for assignee in issue["assignees"]:
                                    participants.add(assignee["login"])
                            issue["participants"] = list(participants)
                    
                    all_issues.extend(issues)
                    
                    if len(issues) < params["per_page"]:
                        break
                    
                    page += 1
                
                logger.info(f"Fetched {len(all_issues)} issues/PRs for {owner}/{repo}")
                return all_issues
                
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error fetching issues for {owner}/{repo}: {e}")
                return []
            except Exception as e:
                logger.error(f"Error fetching issues for {owner}/{repo}: {e}")
                raise
    
    async def _analyze_contributor_concentration(self, owner: str, repo: str, commits: List[Dict], contributors: List[Dict], issues: List[Dict]) -> Dict[str, Any]:
        """Analyze active contributors across commits, issues, and reviews (last year only)"""
        
        # Filter commits and issues to analysis window
        recent_commits = self._filter_recent_commits(commits)
        recent_issues = self._filter_recent_issues(issues)
        
        # Initialize contributor tracking
        active_contributors = {}
        bots_filtered = 0
        
        # Also track activity by time periods for trend analysis
        # Divide the analysis window into 4 quarters
        now = datetime.now()
        cutoff_date = now - timedelta(days=self.analysis_window_days)
        quarter_length = self.analysis_window_days // 4
        
        def get_quarter(date_obj):
            """Get quarter (0-3) for a given date, where 3 is most recent"""
            if isinstance(date_obj, str):
                try:
                    if date_obj.endswith('Z'):
                        date_obj = date_obj[:-1] + '+00:00'
                    date_obj = datetime.fromisoformat(date_obj)
                    if date_obj.tzinfo is not None:
                        date_obj = date_obj.replace(tzinfo=None)
                except:
                    return None
            
            days_ago = (now - date_obj).days
            if days_ago < 0 or days_ago > self.analysis_window_days:
                return None
            quarter = min(3, days_ago // quarter_length)
            return 3 - quarter  # Reverse so quarter 3 is most recent
        
        # 1. Track commit authors
        for commit in recent_commits:
            # Add null checks for commit structure
            if not commit or not isinstance(commit, dict):
                continue
                
            author_info = commit.get("author") or {}
            commit_info = commit.get("commit") or {}
            commit_author = commit_info.get("author") or {}
            
            author_login = author_info.get("login", "unknown")
            author_name = commit_author.get("name", "Unknown")
            author_email = commit_author.get("email", "")
            
            if author_login == "unknown" and author_name != "Unknown":
                author_login = author_name
            
            # Skip bot accounts
            if self._is_bot_account(author_login, author_name, author_email):
                bots_filtered += 1
                continue
            
            if author_login not in active_contributors:
                email_type = self._classify_email_domain(author_email)
                active_contributors[author_login] = {
                    "name": author_name,
                    "email": author_email,
                    "email_type": email_type,
                    "commits": 0,
                    "issues_created": 0,
                    "prs_created": 0,
                    "reviews_given": 0,
                    "comments_made": 0,
                    "total_activity": 0,
                    "quarterly_activity": [0, 0, 0, 0]  # Q0 (oldest) to Q3 (newest)
                }
            
            active_contributors[author_login]["commits"] += 1
            
            # Track quarterly activity for trend analysis
            commit_date = commit_info.get("author", {}).get("date", "")
            quarter = get_quarter(commit_date)
            if quarter is not None:
                active_contributors[author_login]["quarterly_activity"][quarter] += 1
        
        # 2. Track issue and PR authors
        for issue in recent_issues:
            # Add null checks for issue structure
            if not issue or not isinstance(issue, dict):
                continue
                
            user_info = issue.get("user") or {}
            author_login = user_info.get("login", "unknown")
            
            if author_login == "unknown":
                continue
            
            # Skip bot accounts
            if self._is_bot_account(author_login, "", ""):
                bots_filtered += 1
                continue
            
            # Initialize contributor if not seen before
            if author_login not in active_contributors:
                active_contributors[author_login] = {
                    "name": author_login,  # Use login as name if we don't have the real name
                    "email": "",
                    "email_type": "N/A",
                    "commits": 0,
                    "issues_created": 0,
                    "prs_created": 0,
                    "reviews_given": 0,
                    "comments_made": 0,
                    "total_activity": 0,
                    "quarterly_activity": [0, 0, 0, 0]
                }
            
            # Check if it's a PR or issue and track quarterly activity
            created_at = issue.get("created_at", "")
            quarter = get_quarter(created_at)
            
            if issue.get("pull_request"):
                active_contributors[author_login]["prs_created"] += 1
                if quarter is not None:
                    active_contributors[author_login]["quarterly_activity"][quarter] += 1
            else:
                active_contributors[author_login]["issues_created"] += 1
                if quarter is not None:
                    active_contributors[author_login]["quarterly_activity"][quarter] += 1
            
            # Track review participants for PRs
            if issue.get("reviews"):
                for review in issue.get("reviews", []):
                    if not review or not isinstance(review, dict):
                        continue
                    reviewer_info = review.get("user") or {}
                    reviewer_login = reviewer_info.get("login", "unknown")
                    
                    # Skip bots and unknown reviewers
                    if reviewer_login == "unknown" or self._is_bot_account(reviewer_login, "", ""):
                        if reviewer_login != "unknown":
                            bots_filtered += 1
                        continue
                        
                    if reviewer_login != author_login:
                        if reviewer_login not in active_contributors:
                            active_contributors[reviewer_login] = {
                                "name": reviewer_login,
                                "email": "",
                                "email_type": "N/A",
                                "commits": 0,
                                "issues_created": 0,
                                "prs_created": 0,
                                "reviews_given": 0,
                                "comments_made": 0,
                                "total_activity": 0,
                                "quarterly_activity": [0, 0, 0, 0]
                            }
                        active_contributors[reviewer_login]["reviews_given"] += 1
                        # Reviews are associated with the PR creation time for quarterly tracking
                        if quarter is not None:
                            active_contributors[reviewer_login]["quarterly_activity"][quarter] += 1
            
            # Track comment activity (approximate)
            comments_count = issue.get("comments", 0)
            participants = issue.get("participants", [])
            if comments_count > 0 and participants and isinstance(participants, list):
                # Distribute comments among participants (rough approximation)
                # Filter out bots from participants
                human_participants = [p for p in participants if p and isinstance(p, str) and not self._is_bot_account(p, "", "")]
                if human_participants:
                    comments_per_participant = max(1, comments_count // len(human_participants))
                    for participant in human_participants:
                        if participant in active_contributors:
                            active_contributors[participant]["comments_made"] += comments_per_participant
        
        # Calculate total activity for each contributor and determine trends
        for login, contributor in active_contributors.items():
            contributor["total_activity"] = (
                contributor["commits"] + 
                contributor["issues_created"] + 
                contributor["prs_created"] + 
                contributor["reviews_given"] + 
                contributor["comments_made"]
            )
            
            # Calculate trend for contributors with 10+ activities
            if contributor["total_activity"] >= 10:
                quarters = contributor["quarterly_activity"]
                # Compare recent half (Q2+Q3) vs older half (Q0+Q1)
                recent_half = quarters[2] + quarters[3]
                older_half = quarters[0] + quarters[1]
                
                if older_half == 0 and recent_half > 0:
                    trend = "increasing"
                elif recent_half == 0 and older_half > 0:
                    trend = "decreasing"
                elif older_half == 0 and recent_half == 0:
                    trend = "stable"
                else:
                    ratio = recent_half / older_half if older_half > 0 else float('inf')
                    if ratio > 1.5:
                        trend = "increasing"
                    elif ratio < 0.67:
                        trend = "decreasing"
                    else:
                        trend = "stable"
                
                contributor["activity_trend"] = trend
            else:
                contributor["activity_trend"] = "insufficient_data"
        
        # Add sentiment analysis for active contributors
        await self._analyze_contributor_sentiment(owner, repo, active_contributors)
        
        # Calculate overall repository statistics
        repo_stats = self._calculate_repository_statistics(recent_issues, recent_commits)
        
        # Sort contributors by total activity
        sorted_contributors = sorted(
            active_contributors.items(), 
            key=lambda x: x[1]["total_activity"], 
            reverse=True
        )
        
        if not sorted_contributors:
            return {
                "contributor_concentration_risk": 1.0,
                "total_active_contributors": 0,
                "recent_commits_analyzed": len(recent_commits),
                "recent_issues_analyzed": len(recent_issues),
                "active_contributors": [],
                "top_contributor_percentage": 100,
                "activity_distribution": {}
            }
        
        # Calculate statistics
        total_activity = sum(c[1]["total_activity"] for c in sorted_contributors)
        top_contributor = sorted_contributors[0]
        top_contributor_activity = top_contributor[1]["total_activity"]
        top_contributor_percentage = (top_contributor_activity / total_activity * 100) if total_activity > 0 else 0
        
        # Risk calculation: high risk if one person does >70% of activity
        concentration_risk = min(1.0, max(0.0, (top_contributor_percentage - 30) / 40))
        
        # Create contributor list with detailed breakdown
        contributor_list = []
        for login, data in sorted_contributors:
            contributor_info = {
                "login": login,
                "name": data["name"],
                "email": data["email"],
                "email_type": data["email_type"],
                "activity_breakdown": {
                    "commits": data["commits"],
                    "issues_created": data["issues_created"],
                    "prs_created": data["prs_created"],
                    "reviews_given": data["reviews_given"],
                    "comments_made": data["comments_made"]
                },
                "total_activity": data["total_activity"],
                "activity_percentage": (data["total_activity"] / total_activity * 100) if total_activity > 0 else 0,
                "quarterly_activity": data["quarterly_activity"],
                "activity_trend": data["activity_trend"],
                "sentiment_analysis": data.get("sentiment_analysis", {
                    "average_polarity": 0.0,
                    "average_subjectivity": 0.0,
                    "comments_analyzed": 0,
                    "sentiment_label": "no_data"
                })
            }
            contributor_list.append(contributor_info)
        
        # Activity distribution summary
        activity_distribution = {
            "top_1_contributor_percentage": top_contributor_percentage,
            "top_3_contributors_percentage": sum(c[1]["total_activity"] for c in sorted_contributors[:3]) / total_activity * 100 if total_activity > 0 else 0,
            "top_5_contributors_percentage": sum(c[1]["total_activity"] for c in sorted_contributors[:5]) / total_activity * 100 if total_activity > 0 else 0,
        }
        
        result = {
            "contributor_concentration_risk": concentration_risk,
            "total_active_contributors": len(active_contributors),
            "recent_commits_analyzed": len(recent_commits),
            "recent_issues_analyzed": len(recent_issues),
            "total_activity_events": total_activity,
            "repository_statistics": repo_stats,
            "top_contributor": {
                "login": top_contributor[0],
                "name": top_contributor[1]["name"],
                "total_activity": top_contributor_activity,
                "percentage": top_contributor_percentage
            },
            "active_contributors": contributor_list,
            "activity_distribution": activity_distribution
        }
        
        # Contributors summary logged for debugging
        for i, (login, data) in enumerate(sorted_contributors, 1):
            activity_pct = (data["total_activity"] / total_activity * 100) if total_activity > 0 else 0
            trend_text = ""
            if data["total_activity"] >= 10:
                trend = data["activity_trend"]
                if trend == "increasing":
                    trend_text = " (📈 increasing)"
                elif trend == "decreasing":
                    trend_text = " (📉 decreasing)"
                elif trend == "stable":
                    trend_text = " (➡️ stable)"
            
            # Add email type indicator
            email_type = data.get("email_type", "N/A")
            email_indicators = {
                "company": "🏢",
                "personal": "👤", 
                "academic": "🎓",
                "custom": "🏛️",
                "unknown": "❓",
                "N/A": "❌"
            }
            email_icon = email_indicators.get(email_type, "❓")
            
            # Add sentiment indicator
            sentiment_data = data.get("sentiment_analysis", {})
            sentiment_label = sentiment_data.get("sentiment_label", "no_data")
            sentiment_icons = {
                "positive": "😊",
                "negative": "😞", 
                "neutral": "😐",
                "no_recent_comments_found": "🔍",
                "insufficient_activity": "💤",
                "no_data": "❓"
            }
            sentiment_icon = sentiment_icons.get(sentiment_label, "❓")
            sentiment_text = ""
            if sentiment_data.get("comments_analyzed", 0) > 0:
                polarity = sentiment_data.get("average_polarity", 0.0)
                sentiment_text = f" {sentiment_icon} ({sentiment_label}, {polarity:+.2f})"
            elif sentiment_label == "no_recent_comments_found":
                sentiment_text = f" {sentiment_icon} (no recent comments found in sample)"
            elif sentiment_label != "no_data":
                sentiment_text = f" {sentiment_icon} ({sentiment_label})"
            
            # Detailed contributor info removed for production
            
            # Quarterly breakdown and sentiment analysis data is included in the result
            # but not printed to avoid console encoding issues
        
        return result
    
    def _generate_recommendations(self, risk_factors: Dict[str, Any]) -> List[str]:
        """Generate actionable recommendations based on risk factors"""
        recommendations = []
        
        # Get key metrics for analysis
        total_contributors = risk_factors.get("total_active_contributors", 0)
        concentration_risk = risk_factors.get("contributor_concentration_risk", 0)
        top_contributor = risk_factors.get("top_contributor", {})
        repo_stats = risk_factors.get("repository_statistics", {})
        contributors = risk_factors.get("active_contributors", [])
        
        # Primary contributor abandonment/capacity risk
        if concentration_risk > 0.5 and total_contributors <= 3:  # High concentration with few contributors
            if contributors:
                # Find the top contributor and check their details
                top_contributor_data = contributors[0] if contributors else {}
                email_type = top_contributor_data.get("email_type", "")
                activity_trend = top_contributor_data.get("activity_trend", "")
                
                # Check if top contributor is not from a company
                if email_type in ["personal", "N/A", "unknown"]:
                    if activity_trend == "decreasing":
                        recommendations.append("⚠️ ABANDONMENT RISK: Primary contributor (non-company email) shows declining activity - high risk of project abandonment")
                    elif activity_trend in ["stable", "increasing"]:
                        recommendations.append("⚠️ CAPACITY RISK: Project heavily dependent on single non-company contributor - risk of burnout or 'Nebraska problem' (single point of failure)")
        
        # Security risk from slow bot PR responses
        avg_pr_close_time = repo_stats.get("avg_pr_close_time_days")
        if avg_pr_close_time is not None and avg_pr_close_time > 5:
            recommendations.append(f"🔒 SECURITY RISK: Average PR close time ({avg_pr_close_time:.1f} days) exceeds 5 days - security patches may not be applied quickly enough")
        
        # Contributor concentration
        if concentration_risk > 0.7:
            recommendations.append("Consider actively recruiting additional maintainers to reduce dependency on single contributor")
        elif concentration_risk > 0.4:
            recommendations.append("Monitor contributor diversity - one person is doing a significant portion of the work")
        
        # Activity level recommendations
        if total_contributors < 3:
            recommendations.append("Critical: Very few active contributors - prioritize community building and contributor recruitment")
        elif total_contributors < 5:
            recommendations.append("Low contributor count - consider ways to encourage more community participation")
        
        # Activity distribution recommendations
        activity_dist = risk_factors.get("activity_distribution", {})
        top_3_pct = activity_dist.get("top_3_contributors_percentage", 0)
        if top_3_pct > 80:
            recommendations.append("Top 3 contributors handle most activity - implement knowledge sharing and mentoring programs")
        
        if not recommendations:
            recommendations.append("Project shows good contributor diversity and activity distribution")
        
        return recommendations


# MCP Server Implementation
app = Server("project-risk-analyzer")
analyzer = ProjectRiskAnalyzer()

@app.list_tools()
async def handle_list_tools() -> list[Tool]:
    """Return list of available tools"""
    return [
        Tool(
            name="analyze_project_risk",
            description="Analyze repositories for maintainer and contributor sustainability risks",
            inputSchema={
                "type": "object",
                "properties": {
                    "repositories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of repository URLs or owner/repo strings to analyze"
                    }
                },
                "required": ["repositories"]
            }
        )
    ]

@app.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool execution"""
    if name == "analyze_project_risk":
        try:
            repositories = arguments.get("repositories", [])
            
            if not repositories:
                return [TextContent(
                    type="text",
                    text="Error: No repositories provided for analysis"
                )]
            
            # Perform analysis
            analyses = await analyzer.analyze_repositories(repositories)
            
            # Format results
            results = {
                "summary": {
                    "total_repositories": len(analyses),
                    "high_risk_count": sum(1 for a in analyses if a.overall_risk_score > 0.7),
                    "medium_risk_count": sum(1 for a in analyses if 0.3 < a.overall_risk_score <= 0.7),
                    "low_risk_count": sum(1 for a in analyses if a.overall_risk_score <= 0.3)
                },
                "analyses": [
                    {
                        "repository": a.repository,
                        "overall_risk_score": round(a.overall_risk_score, 3),
                        "risk_level": "High" if a.overall_risk_score > 0.7 else "Medium" if a.overall_risk_score > 0.3 else "Low",
                        "key_risk_factors": a.risk_factors,
                        "recommendations": a.recommendations,
                        "analysis_date": a.analysis_date
                    } for a in analyses
                ]
            }
            
            return [TextContent(
                type="text",
                text=json.dumps(results, indent=2)
            )]
            
        except Exception as e:
            logger.error(f"Error in analyze_project_risk: {e}")
            return [TextContent(
                type="text",
                text=f"Error analyzing repositories: {str(e)}"
            )]
    
    return [TextContent(
        type="text",
        text=f"Unknown tool: {name}"
    )]


async def main():
    """Main entry point - run MCP server"""
    # Standard MCP server startup using stdio
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())