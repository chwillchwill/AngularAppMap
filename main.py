#!/usr/bin/env python3
"""
Angular to C# Call Path Analyzer
Discovers and maps application call paths from Angular screens to C# services and underlying classes/methods.
Supports direct and indirect path analysis through code inspection.
"""

import os
import re
import json
import csv
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Any
from collections import defaultdict, deque
from dataclasses import dataclass, asdict
import ast
from html import escape


@dataclass
class CallPath:
    screen: str
    service_method: str
    class_name: str
    method_name: str
    path_type: str  # 'direct' or 'indirect'
    call_chain: List[str]
    file_path: str
    line_number: int


@dataclass
class AnalysisResults:
    direct_paths: List[CallPath]
    indirect_paths: List[CallPath]
    summary: Dict[str, Any]


class CodeAnalyzer:
    def __init__(self, project_root: str, options: Dict[str, Any]):
        self.project_root = Path(project_root)
        self.options = options
        self.logger = self._setup_logging()

        # Pattern collections for different file types
        self.angular_patterns = {
            'component_class': re.compile(r'export\s+class\s+(\w+)(?:Component)?', re.IGNORECASE),
            'service_injection': re.compile(r'(?:constructor|inject)\s*\([^)]*(\w+Service)[^)]*\)', re.IGNORECASE),
            'service_call': re.compile(r'this\.(\w+)\.(\w+)\s*\(', re.IGNORECASE),
            'http_call': re.compile(r'this\.http\.(get|post|put|delete|patch)\s*\(\s*[\'"`]([^\'"`]+)[\'"`]',
                                    re.IGNORECASE),
            'method_definition': re.compile(r'(?:public|private|protected)?\s*(\w+)\s*\([^)]*\)\s*(?::\s*\w+)?\s*\{',
                                            re.IGNORECASE)
        }

        self.csharp_patterns = {
            'class_definition': re.compile(r'(?:public|internal)?\s*class\s+(\w+)(?:\s*:\s*[\w\s,<>]+)?\s*\{',
                                           re.IGNORECASE),
            'method_definition': re.compile(
                r'(?:public|private|protected|internal)?\s*(?:static\s+)?(?:async\s+)?(?:Task<?[\w<>]*>?\s+|void\s+|[\w<>]+\s+)(\w+)\s*\([^)]*\)',
                re.IGNORECASE),
            'method_call': re.compile(r'(?:await\s+)?(?:this\.)?(\w+)\.(\w+)\s*\(', re.IGNORECASE),
            'controller_route': re.compile(r'\[(?:Http(?:Get|Post|Put|Delete|Patch)|Route)\([\'"`]([^\'"`]+)[\'"`]\)\]',
                                           re.IGNORECASE),
            'service_registration': re.compile(r'services\.Add(?:Scoped|Singleton|Transient)<(\w+)(?:,\s*(\w+))?>',
                                               re.IGNORECASE)
        }

        # Storage for discovered elements
        self.angular_components = {}
        self.angular_services = {}
        self.csharp_controllers = {}
        self.csharp_services = {}
        self.csharp_classes = {}
        self.call_paths = []

    def _setup_logging(self) -> logging.Logger:
        logging.basicConfig(
            level=logging.INFO if self.options.get('verbose') else logging.WARNING,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        return logging.getLogger(__name__)

    def analyze_project(self) -> AnalysisResults:
        """Main analysis method that orchestrates the entire process."""
        self.logger.info(f"Starting analysis of project: {self.project_root}")

        # Phase 1: Discover all files and parse them
        self._discover_angular_files()
        self._discover_csharp_files()

        # Phase 2: Build call relationships
        self._build_direct_call_paths()
        self._build_indirect_call_paths()

        # Phase 3: Generate results
        direct_paths = [cp for cp in self.call_paths if cp.path_type == 'direct']
        indirect_paths = [cp for cp in self.call_paths if cp.path_type == 'indirect']

        summary = self._generate_summary(direct_paths, indirect_paths)

        return AnalysisResults(direct_paths, indirect_paths, summary)

    def _discover_angular_files(self):
        """Discover and parse Angular TypeScript files."""
        angular_extensions = {'.ts', '.js'}
        angular_dirs = {'src', 'app', 'components', 'services', 'pages'}

        for file_path in self._find_files_recursive(angular_extensions):
            if any(part in str(file_path).lower() for part in angular_dirs):
                self._parse_angular_file(file_path)

    def _discover_csharp_files(self):
        """Discover and parse C# files."""
        csharp_extensions = {'.cs'}

        for file_path in self._find_files_recursive(csharp_extensions):
            self._parse_csharp_file(file_path)

    def _find_files_recursive(self, extensions: Set[str]) -> List[Path]:
        """Recursively find files with specified extensions."""
        files = []
        for root, dirs, filenames in os.walk(self.project_root):
            # Skip common build/dependency directories
            dirs[:] = [d for d in dirs if d not in {
                'node_modules', 'bin', 'obj', '.git', '.vs', 'dist', 'build',
                'packages', '.angular', '.vscode'
            }]

            for filename in filenames:
                if any(filename.lower().endswith(ext) for ext in extensions):
                    files.append(Path(root) / filename)
        return files

    def _parse_angular_file(self, file_path: Path):
        """Parse Angular TypeScript file for components and services."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Detect if it's a component or service
            if '@Component' in content:
                self._parse_angular_component(file_path, content)
            elif '@Injectable' in content or 'Service' in file_path.name:
                self._parse_angular_service(file_path, content)

        except Exception as e:
            self.logger.warning(f"Error parsing Angular file {file_path}: {e}")

    def _parse_angular_component(self, file_path: Path, content: str):
        """Parse Angular component file."""
        class_match = self.angular_patterns['component_class'].search(content)
        if not class_match:
            return

        component_name = class_match.group(1)

        # Find injected services
        injected_services = []
        for match in self.angular_patterns['service_injection'].finditer(content):
            injected_services.append(match.group(1))

        # Find service method calls
        service_calls = []
        for match in self.angular_patterns['service_call'].finditer(content):
            service_calls.append((match.group(1), match.group(2), match.start()))

        # Find HTTP calls
        http_calls = []
        for match in self.angular_patterns['http_call'].finditer(content):
            http_calls.append((match.group(1), match.group(2), match.start()))

        # Find component methods
        methods = []
        for match in self.angular_patterns['method_definition'].finditer(content):
            methods.append(match.group(1))

        self.angular_components[component_name] = {
            'file_path': str(file_path),
            'injected_services': injected_services,
            'service_calls': service_calls,
            'http_calls': http_calls,
            'methods': methods,
            'content': content
        }

    def _parse_angular_service(self, file_path: Path, content: str):
        """Parse Angular service file."""
        class_match = self.angular_patterns['component_class'].search(content)
        if not class_match:
            return

        service_name = class_match.group(1)

        # Find HTTP calls
        http_calls = []
        for match in self.angular_patterns['http_call'].finditer(content):
            http_calls.append((match.group(1), match.group(2), match.start()))

        # Find service methods
        methods = []
        for match in self.angular_patterns['method_definition'].finditer(content):
            methods.append(match.group(1))

        # Find method calls to other services
        service_calls = []
        for match in self.angular_patterns['service_call'].finditer(content):
            service_calls.append((match.group(1), match.group(2), match.start()))

        self.angular_services[service_name] = {
            'file_path': str(file_path),
            'http_calls': http_calls,
            'methods': methods,
            'service_calls': service_calls,
            'content': content
        }

    def _parse_csharp_file(self, file_path: Path):
        """Parse C# file for controllers, services, and other classes."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Detect file type
            if 'Controller' in content and '[Route' in content:
                self._parse_csharp_controller(file_path, content)
            elif 'Service' in file_path.name or 'service' in content.lower():
                self._parse_csharp_service(file_path, content)
            else:
                self._parse_csharp_class(file_path, content)

        except Exception as e:
            self.logger.warning(f"Error parsing C# file {file_path}: {e}")

    def _parse_csharp_controller(self, file_path: Path, content: str):
        """Parse C# controller file."""
        class_match = self.csharp_patterns['class_definition'].search(content)
        if not class_match:
            return

        controller_name = class_match.group(1)

        # Find routes
        routes = []
        for match in self.csharp_patterns['controller_route'].finditer(content):
            routes.append(match.group(1))

        # Find methods
        methods = []
        for match in self.csharp_patterns['method_definition'].finditer(content):
            methods.append(match.group(1))

        # Find method calls
        method_calls = []
        for match in self.csharp_patterns['method_call'].finditer(content):
            method_calls.append((match.group(1), match.group(2), match.start()))

        self.csharp_controllers[controller_name] = {
            'file_path': str(file_path),
            'routes': routes,
            'methods': methods,
            'method_calls': method_calls,
            'content': content
        }

    def _parse_csharp_service(self, file_path: Path, content: str):
        """Parse C# service file."""
        class_match = self.csharp_patterns['class_definition'].search(content)
        if not class_match:
            return

        service_name = class_match.group(1)

        # Find methods
        methods = []
        for match in self.csharp_patterns['method_definition'].finditer(content):
            methods.append(match.group(1))

        # Find method calls
        method_calls = []
        for match in self.csharp_patterns['method_call'].finditer(content):
            method_calls.append((match.group(1), match.group(2), match.start()))

        self.csharp_services[service_name] = {
            'file_path': str(file_path),
            'methods': methods,
            'method_calls': method_calls,
            'content': content
        }

    def _parse_csharp_class(self, file_path: Path, content: str):
        """Parse general C# class file."""
        class_match = self.csharp_patterns['class_definition'].search(content)
        if not class_match:
            return

        class_name = class_match.group(1)

        # Find methods
        methods = []
        for match in self.csharp_patterns['method_definition'].finditer(content):
            methods.append(match.group(1))

        # Find method calls
        method_calls = []
        for match in self.csharp_patterns['method_call'].finditer(content):
            method_calls.append((match.group(1), match.group(2), match.start()))

        self.csharp_classes[class_name] = {
            'file_path': str(file_path),
            'methods': methods,
            'method_calls': method_calls,
            'content': content
        }

    def _build_direct_call_paths(self):
        """Build direct call paths from Angular components to C# services."""
        for comp_name, comp_data in self.angular_components.items():
            # Check HTTP calls that might map to controller endpoints
            for http_method, endpoint, line_pos in comp_data['http_calls']:
                line_num = comp_data['content'][:line_pos].count('\n') + 1

                # Try to match endpoint to controller routes
                for ctrl_name, ctrl_data in self.csharp_controllers.items():
                    for route in ctrl_data['routes']:
                        if self._endpoints_match(endpoint, route):
                            for method in ctrl_data['methods']:
                                call_path = CallPath(
                                    screen=comp_name,
                                    service_method=f"{http_method.upper()} {endpoint}",
                                    class_name=ctrl_name,
                                    method_name=method,
                                    path_type='direct',
                                    call_chain=[comp_name, f"{http_method} {endpoint}", f"{ctrl_name}.{method}"],
                                    file_path=comp_data['file_path'],
                                    line_number=line_num
                                )
                                self.call_paths.append(call_path)

            # Check service method calls
            for service_name, method_name, line_pos in comp_data['service_calls']:
                line_num = comp_data['content'][:line_pos].count('\n') + 1

                # Find matching Angular service
                if service_name in self.angular_services:
                    service_data = self.angular_services[service_name]
                    if method_name in service_data['methods']:
                        call_path = CallPath(
                            screen=comp_name,
                            service_method=f"{service_name}.{method_name}",
                            class_name=service_name,
                            method_name=method_name,
                            path_type='direct',
                            call_chain=[comp_name, f"{service_name}.{method_name}"],
                            file_path=comp_data['file_path'],
                            line_number=line_num
                        )
                        self.call_paths.append(call_path)

    def _build_indirect_call_paths(self):
        """Build indirect call paths by following the call chain."""
        # Use BFS to find indirect paths
        visited = set()

        for comp_name, comp_data in self.angular_components.items():
            queue = deque([(comp_name, [])])
            comp_visited = set()

            while queue:
                current_name, path = queue.popleft()

                if current_name in comp_visited:
                    continue
                comp_visited.add(current_name)

                # Check Angular services called by current component/service
                current_data = self.angular_components.get(current_name) or self.angular_services.get(current_name)
                if not current_data:
                    continue

                for service_name, method_name, line_pos in current_data.get('service_calls', []):
                    new_path = path + [f"{current_name}", f"{service_name}.{method_name}"]

                    if service_name in self.angular_services:
                        service_data = self.angular_services[service_name]

                        # Check if this service makes HTTP calls (indirect to C#)
                        for http_method, endpoint, _ in service_data.get('http_calls', []):
                            for ctrl_name, ctrl_data in self.csharp_controllers.items():
                                for route in ctrl_data['routes']:
                                    if self._endpoints_match(endpoint, route):
                                        for ctrl_method in ctrl_data['methods']:
                                            final_path = new_path + [f"{http_method} {endpoint}",
                                                                     f"{ctrl_name}.{ctrl_method}"]

                                            call_path = CallPath(
                                                screen=comp_name,
                                                service_method=f"{service_name}.{method_name}",
                                                class_name=ctrl_name,
                                                method_name=ctrl_method,
                                                path_type='indirect',
                                                call_chain=final_path,
                                                file_path=current_data['file_path'],
                                                line_number=current_data['content'][:line_pos].count(
                                                    '\n') + 1 if line_pos else 0
                                            )
                                            self.call_paths.append(call_path)

                        # Continue BFS for deeper chains
                        if len(path) < self.options.get('max_depth', 5):
                            queue.append((service_name, new_path))

    def _endpoints_match(self, angular_endpoint: str, csharp_route: str) -> bool:
        """Check if Angular HTTP endpoint matches C# controller route."""
        # Simple matching - can be enhanced with more sophisticated logic
        angular_clean = angular_endpoint.strip('/').lower()
        csharp_clean = csharp_route.strip('/').lower()

        # Remove parameter placeholders for basic matching
        angular_clean = re.sub(r'\{[^}]+\}', '*', angular_clean)
        csharp_clean = re.sub(r'\{[^}]+\}', '*', csharp_clean)

        return angular_clean == csharp_clean or angular_clean in csharp_clean or csharp_clean in angular_clean

    def _generate_summary(self, direct_paths: List[CallPath], indirect_paths: List[CallPath]) -> Dict[str, Any]:
        """Generate analysis summary."""
        screens = set(cp.screen for cp in direct_paths + indirect_paths)
        services = set(cp.class_name for cp in direct_paths + indirect_paths)

        return {
            'total_screens': len(self.angular_components),
            'total_services': len(self.csharp_services) + len(self.csharp_controllers),
            'screens_with_paths': len(screens),
            'services_called': len(services),
            'direct_paths_count': len(direct_paths),
            'indirect_paths_count': len(indirect_paths),
            'total_paths': len(direct_paths) + len(indirect_paths)
        }


class OutputGenerator:
    def __init__(self, results: AnalysisResults, options: Dict[str, Any]):
        self.results = results
        self.options = options

    def generate_output(self, output_dir: str):
        """Generate output in requested formats."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        formats = self.options.get('output_formats', ['json'])

        if 'json' in formats or 'all' in formats:
            self._generate_json(output_path / 'call_paths.json')

        if 'csv' in formats or 'all' in formats:
            self._generate_csv(output_path / 'call_paths.csv')

        if 'html' in formats or 'all' in formats:
            self._generate_html(output_path / 'call_paths.html')

    def _generate_json(self, file_path: Path):
        """Generate JSON output."""
        data = {
            'summary': self.results.summary,
            'direct_paths': [asdict(cp) for cp in self.results.direct_paths],
            'indirect_paths': [asdict(cp) for cp in self.results.indirect_paths]
        }

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _generate_csv(self, file_path: Path):
        """Generate CSV output."""
        all_paths = self.results.direct_paths + self.results.indirect_paths

        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Screen', 'Service Method', 'Class Name', 'Method Name',
                'Path Type', 'Call Chain', 'File Path', 'Line Number'
            ])

            for cp in all_paths:
                writer.writerow([
                    cp.screen, cp.service_method, cp.class_name, cp.method_name,
                    cp.path_type, ' -> '.join(cp.call_chain), cp.file_path, cp.line_number
                ])

    def _generate_html(self, file_path: Path):
        """Generate HTML output."""
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Angular to C# Call Path Analysis</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .summary {{ background: #f5f5f5; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
        .paths {{ margin-bottom: 30px; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #4CAF50; color: white; }}
        .direct {{ background-color: #e8f5e8; }}
        .indirect {{ background-color: #fff3cd; }}
        .call-chain {{ font-family: monospace; font-size: 0.9em; }}
    </style>
</head>
<body>
    <h1>Angular to C# Call Path Analysis</h1>

    <div class="summary">
        <h2>Summary</h2>
        <p><strong>Total Screens:</strong> {self.results.summary['total_screens']}</p>
        <p><strong>Total Services:</strong> {self.results.summary['total_services']}</p>
        <p><strong>Screens with Paths:</strong> {self.results.summary['screens_with_paths']}</p>
        <p><strong>Services Called:</strong> {self.results.summary['services_called']}</p>
        <p><strong>Direct Paths:</strong> {self.results.summary['direct_paths_count']}</p>
        <p><strong>Indirect Paths:</strong> {self.results.summary['indirect_paths_count']}</p>
        <p><strong>Total Paths:</strong> {self.results.summary['total_paths']}</p>
    </div>

    <div class="paths">
        <h2>Call Paths</h2>
        <table>
            <thead>
                <tr>
                    <th>Screen</th>
                    <th>Service Method</th>
                    <th>Class Name</th>
                    <th>Method Name</th>
                    <th>Path Type</th>
                    <th>Call Chain</th>
                    <th>File Path</th>
                    <th>Line</th>
                </tr>
            </thead>
            <tbody>
"""

        all_paths = sorted(
            self.results.direct_paths + self.results.indirect_paths,
            key=lambda x: (x.screen, x.path_type, x.class_name)
        )

        for cp in all_paths:
            css_class = 'direct' if cp.path_type == 'direct' else 'indirect'
            call_chain = escape(' → '.join(cp.call_chain))

            html_content += f"""
                <tr class="{css_class}">
                    <td>{escape(cp.screen)}</td>
                    <td>{escape(cp.service_method)}</td>
                    <td>{escape(cp.class_name)}</td>
                    <td>{escape(cp.method_name)}</td>
                    <td>{escape(cp.path_type)}</td>
                    <td class="call-chain">{call_chain}</td>
                    <td>{escape(cp.file_path)}</td>
                    <td>{cp.line_number}</td>
                </tr>
"""

        html_content += """
            </tbody>
        </table>
    </div>
</body>
</html>
"""

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(html_content)


def main():
    parser = argparse.ArgumentParser(
        description='Analyze Angular to C# call paths',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python call_path_analyzer.py /path/to/project
  python call_path_analyzer.py /path/to/project --output-formats json csv
  python call_path_analyzer.py /path/to/project --output-formats all --max-depth 3
  python call_path_analyzer.py /path/to/project -o ./analysis_results --verbose
        """
    )

    parser.add_argument('project_root', help='Root directory of the project to analyze')
    parser.add_argument('-o', '--output-dir', default='./call_path_analysis',
                        help='Output directory for results (default: ./call_path_analysis)')
    parser.add_argument('--output-formats', nargs='+', choices=['json', 'csv', 'html', 'all'],
                        default=['json'], help='Output formats (default: json)')
    parser.add_argument('--max-depth', type=int, default=5,
                        help='Maximum depth for indirect call chain analysis (default: 5)')
    parser.add_argument('--verbose', action='store_true',
                        help='Enable verbose logging')
    parser.add_argument('--exclude-dirs', nargs='+', default=[],
                        help='Additional directories to exclude from analysis')

    args = parser.parse_args()

    options = {
        'output_formats': args.output_formats,
        'max_depth': args.max_depth,
        'verbose': args.verbose,
        'exclude_dirs': args.exclude_dirs
    }

    try:
        # Analyze the project
        analyzer = CodeAnalyzer(args.project_root, options)
        results = analyzer.analyze_project()

        # Generate output
        output_generator = OutputGenerator(results, options)
        output_generator.generate_output(args.output_dir)

        print(f"Analysis complete!")
        print(f"Found {results.summary['total_paths']} call paths:")
        print(f"  - {results.summary['direct_paths_count']} direct paths")
        print(f"  - {results.summary['indirect_paths_count']} indirect paths")
        print(f"Results saved to: {args.output_dir}")

    except Exception as e:
        print(f"Error during analysis: {e}")
        return 1

    return 0


if __name__ == '__main__':
    exit(main())