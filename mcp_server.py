#!/usr/bin/env python3
"""
MCP Server for OSS Metrics 
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-oss-contributor-analyzer")

def main():
    """Main entry point - synchronous to match working pattern"""
    logger.info("Starting OSS Contributor Analyzer MCP Server...")
    
    # Check for GitHub token
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        logger.warning("No GITHUB_TOKEN found in environment. API calls will be rate-limited.")
    else:
        logger.info("GitHub token loaded successfully.")
    
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import Tool, TextContent
        from app import ProjectRiskAnalyzer
        
        # Create the server using your working minimal test pattern
        app = Server("oss-contributor-analyzer")
        
        @app.list_tools()
        async def handle_list_tools() -> list[Tool]:
            """Return list of available tools"""
            logger.info("Tools requested by client")
            return [
                Tool(
                    name="analyze_repository_contributors",
                    description="Analyze a GitHub repository for detailed contributor activity and repository statistics over a specified time period. Optionally includes sentiment analysis of contributor comments.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "repository_url": {
                                "type": "string",
                                "description": "GitHub repository URL to analyze (e.g., https://github.com/owner/repo)"
                            },
                            "analysis_days": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 365,
                                "default": 365,
                                "description": "Number of days to look back for activity analysis (1-365 days)"
                            },
                            "include_sentiment": {
                                "type": "boolean",
                                "description": "Whether to include sentiment analysis of contributor comments (slower but more detailed). Default: false"
                            }
                        },
                        "required": ["repository_url"]
                    }
                )
            ]

        @app.call_tool()
        async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
            """Handle tool execution with detailed logging"""
            logger.info(f"Tool called: {name} with arguments: {arguments}")
            
            if name == "analyze_repository_contributors":
                try:
                    repository_url = arguments.get("repository_url")
                    analysis_days = arguments.get("analysis_days", 365)
                    include_sentiment = arguments.get("include_sentiment", False)
                    
                    sentiment_msg = "with sentiment analysis" if include_sentiment else "without sentiment analysis"
                    logger.info(f"Analyzing repository: {repository_url} (last {analysis_days} days, {sentiment_msg})")
                    
                    if not repository_url:
                        return [TextContent(
                            type="text",
                            text="Error: repository_url is required"
                        )]
                    
                    # Initialize analyzer with custom analysis window
                    analyzer = ProjectRiskAnalyzer()
                    analyzer.analysis_window_days = analysis_days
                    
                    # Set performance mode based on sentiment analysis request
                    analyzer.enable_fast_mode = not include_sentiment  # Fast mode when sentiment is NOT requested
                    
                    # Get analysis with timeout protection
                    logger.info("Starting analysis...")
                    try:
                        # Set timeout based on whether sentiment analysis is requested
                        timeout_seconds = 120.0 if include_sentiment else 45.0
                        analysis_result = await asyncio.wait_for(
                            analyzer.analyze_single_repository(repo_url=repository_url),
                            timeout=timeout_seconds
                        )
                        logger.info(f"Analysis completed, result type: {type(analysis_result)}")
                    except asyncio.TimeoutError:
                        logger.warning("Analysis timed out, returning partial results")
                        timeout_msg = "with sentiment analysis" if include_sentiment else "without sentiment analysis"
                        return [TextContent(
                            type="text",
                            text=f"Analysis timed out ({timeout_msg}). Repository analysis is too complex for current time limits. Try reducing analysis_days parameter or use a smaller repository."
                        )]
                    
                    # Convert to dict if it's not already
                    if hasattr(analysis_result, '__dict__'):
                        result_dict = analysis_result.__dict__
                    else:
                        result_dict = analysis_result
                    
                    logger.info(f"Returning data with keys: {list(result_dict.keys()) if isinstance(result_dict, dict) else 'not a dict'}")
                    
                    # Format the results as JSON
                    result_json = json.dumps(result_dict, indent=2, default=str)
                    logger.info(f"JSON result length: {len(result_json)} characters")
                    
                    return [TextContent(
                        type="text",
                        text=result_json
                    )]
                    
                except Exception as e:
                    logger.error(f"Error in analyze_repository_contributors: {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    return [TextContent(
                        type="text",
                        text=f"Error analyzing repository: {str(e)}"
                    )]
            
            logger.warning(f"Unknown tool requested: {name}")
            return [TextContent(
                type="text",
                text=f"Unknown tool: {name}"
            )]
        
        logger.info("Tool handlers registered, starting server...")
        
        # Run the server - use async context but don't complicate initialization
        async def run_server():
            async with stdio_server() as streams:
                read_stream, write_stream = streams
                logger.info("Server streams established, running...")
                # Add minimal initialization options
                from mcp.server.models import InitializationOptions
                from mcp.types import ServerCapabilities
                
                init_options = InitializationOptions(
                    server_name="oss-contributor-analyzer",
                    server_version="1.0.0", 
                    capabilities=ServerCapabilities()
                )
                await app.run(read_stream, write_stream, init_options)
        
        # Run the async server
        asyncio.run(run_server())
        
    except ImportError as e:
        logger.error(f"MCP import error: {e}")
        logger.error("Please install the MCP library: pip install mcp")
    except Exception as e:
        logger.error(f"Server error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")


if __name__ == "__main__":
    main()
