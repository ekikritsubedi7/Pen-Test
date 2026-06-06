#!/usr/bin/env python3
"""
PentestGPT - AI-Powered Autonomous Penetration Testing Agent
Single-file implementation for demonstration purposes
"""

import os
import sys
import json
import time
import uuid
import subprocess
import threading
import queue
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from pathlib import Path
import argparse
import signal

# Try to import optional dependencies
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("[!] requests module not available. Install with: pip install requests")

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.live import Live
    from rich.progress import Progress, SpinnerColumn, TextColumn
    RICH_AVAILABLE = True
    console = Console()
except ImportError:
    RICH_AVAILABLE = False
    console = None
    print("[!] rich module not available. Install with: pip install rich")

# ANSI colors for fallback
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

@dataclass
class Session:
    """Pentest session state"""
    session_id: str
    target: str
    start_time: float
    last_update: float
    commands_executed: List[str]
    findings: List[Dict]
    flags_found: List[str]
    current_context: str
    completed: bool = False
    
    def to_dict(self):
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data):
        return cls(**data)

class ToolExecutor:
    """Execute pentesting tools and commands"""
    
    @staticmethod
    def run_command(cmd: str, timeout: int = 30) -> Tuple[str, str, int]:
        """Execute a shell command and return output"""
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return "", f"Command timed out after {timeout}s", 124
        except Exception as e:
            return "", str(e), 1
    
    @staticmethod
    def nmap_scan(target: str, ports: str = "") -> str:
        """Run nmap scan"""
        if ports:
            cmd = f"nmap -p {ports} -sV -sC {target} 2>/dev/null"
        else:
            cmd = f"nmap -sV -sC {target} 2>/dev/null"
        stdout, stderr, code = ToolExecutor.run_command(cmd, timeout=120)
        return stdout if code == 0 else f"Scan failed: {stderr}"
    
    @staticmethod
    def sqlmap_check(url: str) -> str:
        """Check for SQL injection"""
        cmd = f"sqlmap -u '{url}' --batch --level=1 --risk=1 2>/dev/null"
        stdout, stderr, code = ToolExecutor.run_command(cmd, timeout=180)
        return stdout if code == 0 else f"Check failed: {stderr}"
    
    @staticmethod
    def dirb_scan(target: str) -> str:
        """Directory brute force"""
        cmd = f"gobuster dir -u {target} -w /usr/share/wordlists/dirb/common.txt -t 30 2>/dev/null"
        stdout, stderr, code = ToolExecutor.run_command(cmd, timeout=180)
        return stdout if code == 0 else f"Scan failed: {stderr}"
    
    @staticmethod
    def check_http(target: str) -> str:
        """Check HTTP service"""
        cmd = f"curl -s -I -m 10 http://{target}"
        stdout, stderr, code = ToolExecutor.run_command(cmd)
        return stdout if code == 0 else f"HTTP check failed: {stderr}"
    
    @staticmethod
    def check_https(target: str) -> str:
        """Check HTTPS service"""
        cmd = f"curl -s -I -m 10 -k https://{target}"
        stdout, stderr, code = ToolExecutor.run_command(cmd)
        return stdout if code == 0 else f"HTTPS check failed: {stderr}"

class LLMProvider:
    """Mock LLM provider - replace with actual API calls"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4"):
        self.api_key = api_key
        self.model = model
        self.conversation_history = []
        
    def reason(self, prompt: str, context: str = "") -> str:
        """
        Generate reasoning for next pentest actions
        This is a mock implementation - replace with actual LLM API
        """
        
        # Mock responses based on prompt content
        prompt_lower = prompt.lower()
        
        if "initial plan" in prompt_lower:
            return """
            Initial reconnaissance plan:
            1. Perform nmap scan to discover open ports
            2. Check HTTP/HTTPS services if ports 80/443 are open
            3. Look for common vulnerabilities based on service versions
            4. Check for default credentials
            5. Attempt directory enumeration
            """
        
        elif "nmap results" in prompt_lower:
            return """
            Based on the scan:
            1. Focus on web services first (HTTP/HTTPS)
            2. Run directory busting on discovered web servers
            3. Check for SQL injection on input parameters
            4. Look for administrative interfaces
            """
        
        elif "sql" in prompt_lower or "injection" in prompt_lower:
            return """
            SQL injection testing strategy:
            1. Test all input parameters with SQL payloads
            2. Check error-based injection points
            3. Attempt union-based extraction
            4. Try time-based blind injection
            5. Look for database version disclosure
            """
        
        elif "directory" in prompt_lower or "gobuster" in prompt_lower:
            return """
            Directory enumeration next steps:
            1. Check discovered directories for common files
            2. Look for backup files or config files
            3. Search for admin panels
            4. Test for file inclusion vulnerabilities
            """
        
        elif "flag" in prompt_lower:
            return "Potential flag found! Check output for flag pattern."
        
        else:
            return """
            Continue systematic testing:
            1. Enumerate all discovered services
            2. Check for version-specific exploits
            3. Test privilege escalation vectors
            4. Document all findings
            """

class PentestGPTAgent:
    """Main autonomous pentesting agent"""
    
    def __init__(self, target: str, instruction: str = "", non_interactive: bool = False):
        self.target = target
        self.instruction = instruction
        self.non_interactive = non_interactive
        self.session = self._create_session()
        self.llm = LLMProvider()
        self.executor = ToolExecutor()
        self.paused = False
        self.running = True
        self.background_tasks = []
        
    def _create_session(self) -> Session:
        """Create new session"""
        session_id = str(uuid.uuid4())[:8]
        return Session(
            session_id=session_id,
            target=self.target,
            start_time=time.time(),
            last_update=time.time(),
            commands_executed=[],
            findings=[],
            flags_found=[],
            current_context="Initializing"
        )
    
    def save_session(self):
        """Save session to disk"""
        session_dir = Path.home() / ".pentestgpt" / "sessions"
        session_dir.mkdir(parents=True, exist_ok=True)
        
        session_file = session_dir / f"{self.session.session_id}.json"
        with open(session_file, 'w') as f:
            json.dump(self.session.to_dict(), f, indent=2)
            
    def load_session(self, session_id: str) -> bool:
        """Load existing session"""
        session_file = Path.home() / ".pentestgpt" / "sessions" / f"{session_id}.json"
        if session_file.exists():
            with open(session_file, 'r') as f:
                data = json.load(f)
                self.session = Session.from_dict(data)
                return True
        return False
    
    def log_finding(self, finding_type: str, details: str, severity: str = "INFO"):
        """Log a finding"""
        finding = {
            "timestamp": time.time(),
            "type": finding_type,
            "details": details,
            "severity": severity
        }
        self.session.findings.append(finding)
        
        if RICH_AVAILABLE:
            color = {"INFO": "blue", "WARNING": "yellow", "CRITICAL": "red"}.get(severity, "white")
            console.print(f"[{color}]✓ {finding_type}: {details[:100]}{'...' if len(details) > 100 else ''}[/{color}]")
        else:
            print(f"{Colors.GREEN}✓ {finding_type}: {details[:100]}{Colors.RESET}")
    
    def detect_flag(self, output: str) -> Optional[str]:
        """Detect flag patterns in output"""
        import re
        # Common flag patterns
        patterns = [
            r'flag\{[^}]+\}',
            r'FLAG\{[^}]+\}',
            r'[A-F0-9]{32}',
            r'[a-f0-9]{64}',
            r'CTF\{[^}]+\}'
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, output)
            if matches:
                for match in matches:
                    if match not in self.session.flags_found:
                        self.session.flags_found.append(match)
                        self.log_finding("FLAG_FOUND", match, "CRITICAL")
                return matches[0]
        return None
    
    def execute_recon(self) -> Dict:
        """Execute initial reconnaissance"""
        findings = {}
        
        # Check if target is reachable
        if RICH_AVAILABLE:
            console.print(Panel(f"[bold cyan]Starting recon on {self.target}[/bold cyan]", border_style="cyan"))
        
        # HTTP check
        http_result = self.executor.check_http(self.target)
        if "200" in http_result or "403" in http_result or "401" in http_result:
            findings['http'] = "HTTP service accessible"
            self.log_finding("HTTP_SERVICE", f"Port 80 open on {self.target}", "INFO")
        
        # HTTPS check
        https_result = self.executor.check_https(self.target)
        if "200" in https_result or "403" in https_result:
            findings['https'] = "HTTPS service accessible"
            self.log_finding("HTTPS_SERVICE", f"Port 443 open on {self.target}", "INFO")
        
        # Nmap scan
        nmap_result = self.executor.nmap_scan(self.target)
        if nmap_result and "open" in nmap_result.lower():
            findings['nmap'] = nmap_result
            self.log_finding("PORT_SCAN", f"Open ports discovered:\n{nmap_result[:500]}", "INFO")
            self.detect_flag(nmap_result)
        
        # Directory scan if web services found
        if findings.get('http') or findings.get('https'):
            protocol = "https" if findings.get('https') else "http"
            url = f"{protocol}://{self.target}"
            dir_result = self.executor.dirb_scan(url)
            if dir_result:
                findings['directories'] = dir_result
                self.log_finding("DIRECTORY_ENUM", f"Discovered directories:\n{dir_result[:500]}", "INFO")
                self.detect_flag(dir_result)
        
        return findings
    
    def exploit_web(self, findings: Dict) -> Dict:
        """Web exploitation phase"""
        exploits = {}
        
        if 'http' in findings or 'https' in findings:
            protocol = "https" if findings.get('https') else "http"
            url = f"{protocol}://{self.target}"
            
            # SQL injection test
            sql_result = self.executor.sqlmap_check(url)
            if sql_result and "vulnerable" in sql_result.lower():
                exploits['sql_injection'] = sql_result
                self.log_finding("SQL_INJECTION", "SQL injection vulnerability found!", "CRITICAL")
                self.detect_flag(sql_result)
            
            # Additional web testing would go here
        
        return exploits
    
    def privilege_escalation(self) -> Dict:
        """Privilege escalation attempts"""
        pe_results = {}
        
        # Check sudo permissions
        sudo_cmd = "sudo -l 2>/dev/null"
        sudo_out, sudo_err, sudo_code = self.executor.run_command(sudo_cmd)
        
        if sudo_out and "(ALL)" in sudo_out:
            pe_results['sudo'] = sudo_out
            self.log_finding("PRIV_ESC", "User has sudo privileges!", "CRITICAL")
            self.detect_flag(sudo_out)
        
        # Check SUID binaries
        suid_cmd = "find / -perm -4000 -type f 2>/dev/null | head -20"
        suid_out, suid_err, suid_code = self.executor.run_command(suid_cmd)
        if suid_out:
            pe_results['suid'] = suid_out
            self.log_finding("SUID_BINARIES", f"SUID binaries found:\n{suid_out}", "WARNING")
        
        return pe_results
    
    def run_autonomous(self):
        """Main autonomous pentest loop"""
        
        if RICH_AVAILABLE:
            console.print(Panel.fit("[bold green]🤖 PentestGPT Agent Starting[/bold green]", border_style="green"))
            console.print(f"[yellow]Target:[/yellow] {self.target}")
            if self.instruction:
                console.print(f"[yellow]Instruction:[/yellow] {self.instruction}")
            console.print("")
        
        # Phase 1: Reconnaissance
        findings = self.execute_recon()
        
        if not findings:
            self.log_finding("RECON_FAILURE", "No services discovered", "WARNING")
            if self.non_interactive:
                print("No services found. Exiting.")
                return
        
        # Phase 2: Exploitation
        if 'http' in findings or 'https' in findings:
            exploits = self.exploit_web(findings)
            findings.update(exploits)
        
        # Phase 3: Privilege Escalation (if local access)
        pe_results = self.privilege_escalation()
        findings.update(pe_results)
        
        # Phase 4: LLM-guided analysis
        if not self.non_interactive:
            analysis_prompt = f"""
            Target: {self.target}
            Findings: {json.dumps(findings, indent=2)}
            Flags found: {self.session.flags_found}
            Instruction: {self.instruction}
            
            Analyze these results and suggest next steps.
            """
            suggestions = self.llm.reason(analysis_prompt)
            
            if RICH_AVAILABLE:
                console.print(Panel(suggestions, title="[bold]🤔 AI Analysis[/bold]", border_style="cyan"))
            else:
                print(f"\n{Colors.CYAN}AI Analysis:{Colors.RESET}\n{suggestions}")
        
        # Summary
        self.session.completed = True
        self.save_session()
        
        if RICH_AVAILABLE:
            summary_table = Table(title="Pentest Summary")
            summary_table.add_column("Metric", style="cyan")
            summary_table.add_column("Value", style="green")
            summary_table.add_row("Target", self.target)
            summary_table.add_row("Flags Found", str(len(self.session.flags_found)))
            summary_table.add_row("Findings", str(len(self.session.findings)))
            summary_table.add_row("Duration", f"{time.time() - self.session.start_time:.1f}s")
            console.print(summary_table)
            
            if self.session.flags_found:
                console.print(Panel.fit("[bold green]🎯 Flags Captured![/bold green]", border_style="green"))
                for flag in self.session.flags_found:
                    console.print(f"  • {flag}")
        else:
            print(f"\n{Colors.BOLD}=== Pentest Summary ==={Colors.RESET}")
            print(f"Target: {self.target}")
            print(f"Flags Found: {len(self.session.flags_found)}")
            print(f"Findings: {len(self.session.findings)}")
            if self.session.flags_found:
                print(f"{Colors.GREEN}Flags: {', '.join(self.session.flags_found)}{Colors.RESET}")

class TUI:
    """Text User Interface for PentestGPT"""
    
    def __init__(self):
        self.agent = None
        
    def run(self, target: str, instruction: str = "", non_interactive: bool = False):
        """Run the TUI"""
        
        if non_interactive:
            agent = PentestGPTAgent(target, instruction, non_interactive=True)
            agent.run_autonomous()
            return
        
        # Interactive mode
        agent = PentestGPTAgent(target, instruction)
        
        if RICH_AVAILABLE:
            console.print(Panel.fit(
                "[bold blue]PentestGPT Interactive Mode[/bold blue]\n"
                "Press Ctrl+P to pause/resume | Ctrl+C to quit",
                border_style="blue"
            ))
        
        try:
            agent.run_autonomous()
        except KeyboardInterrupt:
            if RICH_AVAILABLE:
                console.print("\n[yellow]Session paused. Run 'pentestgpt --resume' to continue[/yellow]")
            else:
                print(f"\n{Colors.YELLOW}Session paused. Run 'pentestgpt --resume' to continue{Colors.RESET}")
            agent.save_session()

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="PentestGPT - AI-Powered Penetration Testing")
    parser.add_argument("--target", "-t", help="Target IP or domain")
    parser.add_argument("--instruction", "-i", help="Additional context or instructions")
    parser.add_argument("--non-interactive", "-n", action="store_true", help="Run in non-interactive mode")
    parser.add_argument("--resume", "-r", help="Resume session ID")
    parser.add_argument("--no-telemetry", action="store_true", help="Disable telemetry")
    parser.add_argument("--version", "-v", action="store_true", help="Show version")
    
    args = parser.parse_args()
    
    if args.version:
        print("PentestGPT v1.0.0 - AI-Powered Autonomous Penetration Testing Agent")
        print("Published at USENIX Security 2024")
        sys.exit(0)
    
    if args.resume:
        # Resume session logic
        print(f"Resuming session {args.resume}...")
        # Implementation would load session and continue
        sys.exit(0)
    
    if not args.target:
        parser.print_help()
        print("\nError: --target is required")
        sys.exit(1)
    
    # Check dependencies
    if not REQUESTS_AVAILABLE:
        print(f"{Colors.YELLOW}Warning: requests module not available. Some features may be limited.{Colors.RESET}")
    
    # Run PentestGPT
    tui = TUI()
    tui.run(args.target, args.instruction or "", args.non_interactive)

if __name__ == "__main__":
    # Setup signal handlers
    def signal_handler(sig, frame):
        print(f"\n{Colors.YELLOW}Interrupted. Exiting...{Colors.RESET}")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    main()
