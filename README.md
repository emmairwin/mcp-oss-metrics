# OSS Metrics MCP Server

A Model Context Protocol (MCP) server that analyzes GitHub repositories for contributor activity, sentiment analysis, and project health metrics.

## Features

- **Complete contributor analysis** - Activity trends and patterns
- **Email domain classification** - Company/personal/academic contributor categorization  
- **Sentiment analysis** - Comment and interaction sentiment analysis
- **Repository statistics** - Response times, close rates, commit frequency
- **Risk assessment** - Project sustainability and health metrics
- **Custom domain filtering** - Configure company domains for analysis

## Tools

### `analyze_repository_contributors`
Analyze a single GitHub repository for detailed contributor activity and metrics. 

**Parameters:**
- `repository_url` (required): GitHub repository URL to analyze
- `analysis_days` (optional): Number of days to look back (1-365, default: 365)  
- `include_sentiment` (optional): Whether to include sentiment analysis (default: false, slower but more detailed)

### `analyze_multiple_repositories` 
Analyze and compare multiple GitHub repositories.

## Setup

### Prerequisites

1. **Python Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **GitHub Token**: Create a `.env` file with your GitHub token:
   ```bash
   cp .env.example .env
   # Edit .env and add your GitHub token
   ```

3. **Quick Setup**: Use the setup script:
   ```bash
   ./setup.sh
   ```

### Running the MCP Server

```bash
# Activate environment
./activate.sh

# Run MCP server
python3 mcp_server.py
```
1. **Python 3.9+**
2. **GitHub Personal Access Token** - Create at [GitHub Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/emmairwin/mcp-oss-metrics.git
cd mcp-oss-metrics

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up environment variables
cp .env.example .env
# Edit .env and add your GitHub token

# 4. Test the server
python test_server.py
```

**Note**: The MCP server is designed to be used with an MCP client (like Claude Desktop). Running `python mcp_server.py` directly will start the server and wait for MCP client connections via stdio.

### Configure with Claude Desktop

Add to your Claude Desktop MCP configuration:

```json
{
  "mcpServers": {
    "oss-metrics": {
      "command": "python",
      "args": ["/path/to/mcp-oss-metrics/mcp_server.py"],
      "env": {
        "GITHUB_TOKEN": "your_github_token_here"
      }
    }
  }
}
```

**Windows users**: Use the full path to your Python executable:
```json
{
  "mcpServers": {
    "oss-metrics": {
      "command": "C:\\Python313\\python.exe",
      "args": ["C:\\path\\to\\mcp-oss-metrics\\mcp_server.py"],
      "env": {
        "GITHUB_TOKEN": "your_github_token_here"
      }
    }
  }
}
```

## Usage

Ask Claude to analyze repositories:
- "Analyze the contributors of https://github.com/microsoft/vscode for the last 90 days"
- "Analyze https://github.com/facebook/react with sentiment analysis included"
- "Compare contributor activity between https://github.com/facebook/react and https://github.com/vuejs/vue"
- "What are the sustainability risks for this repository?"
- "Has Emma Irwin contributed to x repository in the last 100 days?"
- "Is Emma's contribution activity increasing or decreasing?"

**Note:** Sentiment analysis is optional and significantly slower. Only request it when you need detailed sentiment insights about contributor interactions.

## Environment Variables

- `GITHUB_TOKEN` - Required: GitHub Personal Access Token for API access
- `GITHUB_API_URL` - Optional: Custom GitHub API URL (defaults to https://api.github.com)

## Analysis Output

The server provides comprehensive repository analysis including:

- **Contributor Activity**: Detailed metrics for each contributor
- **Email Domain Analysis**: Company vs personal contributor classification
- **Sentiment Analysis**: Comment and interaction sentiment scoring
- **Risk Assessment**: Project sustainability and health metrics
- **Temporal Trends**: Activity patterns over time[text](vscode-local:/c%3A/Users/emmai/Downloads/CODE_OF_CONDUCT.MD)
