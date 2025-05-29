#!/usr/bin/env python3
"""
Angular to C# Call Path Mapper
Maps application call paths from Angular screens to C# services and underlying classes/methods.
Supports both direct and indirect paths with recursive project traversal.
"""

import os
import re
import json
import csv
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict
import html

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class ServiceCall:
    """Represents a service call with its details"""
    service_name: str
    method_name: str
    file_path: str
    line_number: int
    call_type: str  # 'direct' or 'indirect'


@dataclass
class CSharpMethod:
    """Represents a C# method"""
    class_name: str
    method_name: str
    file_path: str
    line_number: int
    parameters: List[str]
    return_type: str


@dataclass
class AngularScreen:
    """Represents an Angular screen/component"""
    component_name: str
    file_path: str
    template_path: Optional[str]
    service_calls: List[ServiceCall]
    indirect_calls: List[ServiceCall]


class CodeAnalyzer:
    """Main analyzer class for mapping Angular to C# call paths"""

    def __init__(self, angular_path: str, csharp_path: str, output_formats: List[str],
                 max_depth: int = 10, include_tests: bool = False):
        self.angular_path = Path(angular_path)
        self.csharp_path = Path(csharp_path)
        self.output_formats = output_formats
        self.max_depth = max_depth
        self.include_tests = include_tests

        # Data structures
        self.angular_components: Dict[str, AngularScreen] = {}
        self.angular_services: Dict[str, Dict] = {}
        self.csharp_methods: Dict[str, List[CSharpMethod]] = defaultdict(list)
        self.service_mappings: Dict[str, str] = {}  # Angular service -> C# controller/service

    def analyze(self) -> Dict:
        """Main analysis method"""
        logger.info("Starting Angular to C# call path analysis...")

        # Step 1: Analyze Angular components and services
        self._analyze_angular_components()
        self._analyze_angular_services()

        # Step 2: Analyze C# controllers and services
        self._analyze_csharp_files()

        # Step 3: Map service calls to C# methods
        self._map_service_calls()

        # Step 4: Build call path mappings
        results = self._build_call_mappings()

        logger.info(f"Analysis complete. Found {len(self.angular_components)} components.")
        return results

    def _analyze_angular_components(self):
        """Analyze Angular components (.ts files)"""
        logger.info("Analyzing Angular components...")

        for ts_file in self.angular_path.rglob("*.component.ts"):
            if not self.include_tests and ('.spec.' in str(ts_file) or 'test' in str(ts_file).lower()):
                continue

            try:
                with open(ts_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                component_name = self._extract_component_name(content, ts_file.name)
                template_path = self._find_template_path(ts_file, content)

                # Extract service calls
                service_calls = self._extract_service_calls(content, str(ts_file))

                screen = AngularScreen(
                    component_name=component_name,
                    file_path=str(ts_file),
                    template_path=template_path,
                    service_calls=service_calls,
                    indirect_calls=[]
                )

                self.angular_components[component_name] = screen

            except Exception as e:
                logger.warning(f"Error analyzing component {ts_file}: {e}")

    def _analyze_angular_services(self):
        """Analyze Angular services"""
        logger.info("Analyzing Angular services...")

        for ts_file in self.angular_path.rglob("*.service.ts"):
            if not self.include_tests and ('.spec.' in str(ts_file) or 'test' in str(ts_file).lower()):
                continue

            try:
                with open(ts_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                service_name = self._extract_service_name(content, ts_file.name)
                methods = self._extract_service_methods(content)
                http_calls = self._extract_http_calls(content, str(ts_file))

                self.angular_services[service_name] = {
                    'file_path': str(ts_file),
                    'methods': methods,
                    'http_calls': http_calls
                }

            except Exception as e:
                logger.warning(f"Error analyzing service {ts_file}: {e}")

    def _analyze_csharp_files(self):
        """Analyze C# controllers and services"""
        logger.info("Analyzing C# files...")

        # Analyze controllers
        for cs_file in self.csharp_path.rglob("*.cs"):
            if not self.include_tests and ('test' in str(cs_file).lower() or 'spec' in str(cs_file).lower()):
                continue

            try:
                with open(cs_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Extract classes and methods
                classes = self._extract_csharp_classes(content, str(cs_file))
                for class_info in classes:
                    class_name = class_info['name']
                    for method in class_info['methods']:
                        csharp_method = CSharpMethod(
                            class_name=class_name,
                            method_name=method['name'],
                            file_path=str(cs_file),
                            line_number=method['line_number'],
                            parameters=method['parameters'],
                            return_type=method['return_type']
                        )
                        self.csharp_methods[class_name].append(csharp_method)

            except Exception as e:
                logger.warning(f"Error analyzing C# file {cs_file}: {e}")

    def _extract_component_name(self, content: str, filename: str) -> str:
        """Extract Angular component name"""
        # Try to find class declaration
        class_match = re.search(r'export\s+class\s+(\w+)(?:\s+implements|\s+extends|\s*{)', content)
        if class_match:
            return class_match.group(1)

        # Fallback to filename
        return filename.replace('.component.ts', '').replace('-', '_').title() + 'Component'

    def _extract_service_name(self, content: str, filename: str) -> str:
        """Extract Angular service name"""
        # Try to find class declaration
        class_match = re.search(r'export\s+class\s+(\w+)(?:\s+implements|\s+extends|\s*{)', content)
        if class_match:
            return class_match.group(1)

        # Fallback to filename
        return filename.replace('.service.ts', '').replace('-', '_').title() + 'Service'

    def _find_template_path(self, component_file: Path, content: str) -> Optional[str]:
        """Find template path for component"""
        # Check for templateUrl in component decorator
        template_match = re.search(r'templateUrl:\s*[\'"`]([^\'"`]+)[\'"`]', content)
        if template_match:
            template_path = component_file.parent / template_match.group(1)
            if template_path.exists():
                return str(template_path)

        # Check for .html file with same name
        html_file = component_file.with_suffix('.html')
        if html_file.exists():
            return str(html_file)

        return None

    def _extract_service_calls(self, content: str, file_path: str) -> List[ServiceCall]:
        """Extract service method calls from component"""
        service_calls = []
        lines = content.split('\n')

        # Find injected services
        injected_services = self._find_injected_services(content)

        for line_num, line in enumerate(lines, 1):
            # Look for service method calls
            for service_var, service_type in injected_services.items():
                # Pattern: this.serviceVariable.methodName() or serviceVariable.methodName()
                patterns = [
                    rf'\b{service_var}\.(\w+)\s*\(',
                    rf'this\.{service_var}\.(\w+)\s*\('
                ]

                for pattern in patterns:
                    matches = re.finditer(pattern, line)
                    for match in matches:
                        method_name = match.group(1)
                        service_call = ServiceCall(
                            service_name=service_type,
                            method_name=method_name,
                            file_path=file_path,
                            line_number=line_num,
                            call_type='direct'
                        )
                        service_calls.append(service_call)

        return service_calls

    def _find_injected_services(self, content: str) -> Dict[str, str]:
        """Find injected services in constructor or properties"""
        services = {}

        # Constructor injection pattern
        constructor_match = re.search(r'constructor\s*\([^)]*\)\s*{', content, re.DOTALL)
        if constructor_match:
            constructor_content = constructor_match.group(0)
            # Match patterns like: private userService: UserService
            service_matches = re.finditer(
                r'(?:private|public|protected)?\s*(\w+)\s*:\s*(\w+)',
                constructor_content
            )
            for match in service_matches:
                var_name = match.group(1)
                service_type = match.group(2)
                if service_type.endswith('Service'):
                    services[var_name] = service_type

        # Property injection (Angular 14+)
        property_matches = re.finditer(
            r'(\w+)\s*=\s*inject\s*\(\s*(\w+)\s*\)',
            content
        )
        for match in property_matches:
            var_name = match.group(1)
            service_type = match.group(2)
            services[var_name] = service_type

        return services

    def _extract_service_methods(self, content: str) -> List[Dict]:
        """Extract methods from Angular service"""
        methods = []
        lines = content.split('\n')

        for line_num, line in enumerate(lines, 1):
            # Match method declarations
            method_match = re.match(r'\s*(\w+)\s*\([^)]*\)\s*:\s*(\w+|Observable<\w+>|Promise<\w+>)', line.strip())
            if method_match:
                method_name = method_match.group(1)
                return_type = method_match.group(2)

                # Skip common non-method keywords
                if method_name not in ['if', 'for', 'while', 'switch', 'catch', 'constructor']:
                    methods.append({
                        'name': method_name,
                        'return_type': return_type,
                        'line_number': line_num
                    })

        return methods

    def _extract_http_calls(self, content: str, file_path: str) -> List[Dict]:
        """Extract HTTP calls from service"""
        http_calls = []
        lines = content.split('\n')

        for line_num, line in enumerate(lines, 1):
            # Match HTTP method calls
            http_patterns = [
                r'this\.http\.(get|post|put|delete|patch)\s*\(\s*[\'"`]([^\'"`]+)[\'"`]',
                r'http\.(get|post|put|delete|patch)\s*\(\s*[\'"`]([^\'"`]+)[\'"`]'
            ]

            for pattern in http_patterns:
                matches = re.finditer(pattern, line)
                for match in matches:
                    http_method = match.group(1).upper()
                    url = match.group(2)

                    http_calls.append({
                        'method': http_method,
                        'url': url,
                        'line_number': line_num
                    })

        return http_calls

    def _extract_csharp_classes(self, content: str, file_path: str) -> List[Dict]:
        """Extract C# classes and their methods"""
        classes = []
        lines = content.split('\n')

        current_class = None
        brace_count = 0
        in_class = False

        for line_num, line in enumerate(lines, 1):
            stripped_line = line.strip()

            # Skip comments and empty lines
            if not stripped_line or stripped_line.startswith('//') or stripped_line.startswith('*'):
                continue

            # Class declaration
            class_match = re.search(r'(?:public|internal|private)?\s*class\s+(\w+)', stripped_line)
            if class_match and not in_class:
                class_name = class_match.group(1)
                current_class = {
                    'name': class_name,
                    'line_number': line_num,
                    'methods': []
                }
                in_class = True
                brace_count = 0

            # Track braces to know when class ends
            brace_count += line.count('{') - line.count('}')

            # Method declaration within class
            if in_class and current_class:
                method_match = re.search(
                    r'(?:public|private|protected|internal)?\s*(?:static\s+)?(?:async\s+)?(\w+(?:<[\w,\s]+>)?)\s+(\w+)\s*\([^)]*\)',
                    stripped_line
                )

                if method_match and not any(keyword in stripped_line for keyword in ['class', 'interface', 'enum']):
                    return_type = method_match.group(1)
                    method_name = method_match.group(2)

                    # Skip constructors and common non-method keywords
                    if method_name != current_class['name'] and method_name not in ['if', 'for', 'while', 'switch']:
                        # Extract parameters
                        param_match = re.search(r'\(([^)]*)\)', stripped_line)
                        parameters = []
                        if param_match and param_match.group(1).strip():
                            param_str = param_match.group(1)
                            # Simple parameter extraction
                            for param in param_str.split(','):
                                param = param.strip()
                                if param:
                                    parameters.append(param)

                        current_class['methods'].append({
                            'name': method_name,
                            'return_type': return_type,
                            'parameters': parameters,
                            'line_number': line_num
                        })

            # End of class
            if in_class and brace_count <= 0 and current_class:
                classes.append(current_class)
                current_class = None
                in_class = False

        return classes

    def _map_service_calls(self):
        """Map Angular service calls to C# methods"""
        logger.info("Mapping service calls to C# methods...")

        for service_name, service_info in self.angular_services.items():
            for http_call in service_info['http_calls']:
                url = http_call['url']
                method = http_call['method']

                # Try to match URL to C# controller action
                csharp_match = self._find_matching_csharp_method(url, method)
                if csharp_match:
                    key = f"{service_name}.{method}_{url}"
                    self.service_mappings[key] = csharp_match

    def _find_matching_csharp_method(self, url: str, http_method: str) -> Optional[str]:
        """Find matching C# method for HTTP call"""
        # Simple URL matching - can be enhanced based on routing patterns
        url_parts = [part for part in url.split('/') if part and not part.startswith('{')]

        for class_name, methods in self.csharp_methods.items():
            if 'controller' in class_name.lower():
                for method in methods:
                    # Match by method name similarity to URL parts
                    method_lower = method.method_name.lower()
                    if any(part.lower() in method_lower for part in url_parts):
                        return f"{class_name}.{method.method_name}"

        return None

    def _build_call_mappings(self) -> Dict:
        """Build the final call path mappings"""
        results = {
            'components': {},
            'summary': {
                'total_components': len(self.angular_components),
                'total_services': len(self.angular_services),
                'total_csharp_classes': len(self.csharp_methods)
            }
        }

        for component_name, component in self.angular_components.items():
            # Find indirect calls through services
            indirect_calls = self._find_indirect_calls(component)
            component.indirect_calls = indirect_calls

            results['components'][component_name] = {
                'file_path': component.file_path,
                'template_path': component.template_path,
                'direct_calls': [asdict(call) for call in component.service_calls],
                'indirect_calls': [asdict(call) for call in component.indirect_calls],
                'csharp_mappings': self._get_csharp_mappings(component)
            }

        return results

    def _find_indirect_calls(self, component: AngularScreen) -> List[ServiceCall]:
        """Find indirect service calls through other services"""
        indirect_calls = []

        for direct_call in component.service_calls:
            service_name = direct_call.service_name
            method_name = direct_call.method_name

            # Look for this service method's HTTP calls
            if service_name in self.angular_services:
                service_info = self.angular_services[service_name]
                for http_call in service_info['http_calls']:
                    indirect_call = ServiceCall(
                        service_name=f"{service_name}.{method_name}",
                        method_name=f"{http_call['method']} {http_call['url']}",
                        file_path=service_info['file_path'],
                        line_number=http_call['line_number'],
                        call_type='indirect'
                    )
                    indirect_calls.append(indirect_call)

        return indirect_calls

    def _get_csharp_mappings(self, component: AngularScreen) -> List[Dict]:
        """Get C# method mappings for a component"""
        mappings = []

        for indirect_call in component.indirect_calls:
            if indirect_call.call_type == 'indirect':
                # Try to find matching C# method
                method_parts = indirect_call.method_name.split(' ', 1)
                if len(method_parts) == 2:
                    http_method, url = method_parts
                    csharp_match = self._find_matching_csharp_method(url, http_method)
                    if csharp_match:
                        class_name, method_name = csharp_match.split('.', 1)
                        csharp_methods = self.csharp_methods.get(class_name, [])
                        for method in csharp_methods:
                            if method.method_name == method_name:
                                mappings.append({
                                    'csharp_class': class_name,
                                    'csharp_method': method_name,
                                    'file_path': method.file_path,
                                    'line_number': method.line_number,
                                    'parameters': method.parameters,
                                    'return_type': method.return_type,
                                    'angular_call': indirect_call.method_name
                                })
                                break

        return mappings


class OutputGenerator:
    """Generates output in various formats"""

    def __init__(self, results: Dict, output_dir: str):
        self.results = results
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_all(self, formats: List[str]):
        """Generate output in all requested formats"""
        for format_type in formats:
            if format_type.lower() == 'json':
                self.generate_json()
            elif format_type.lower() == 'csv':
                self.generate_csv()
            elif format_type.lower() == 'html':
                self.generate_html()

    def generate_json(self):
        """Generate JSON output"""
        output_file = self.output_dir / 'call_mappings.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        logger.info(f"JSON output generated: {output_file}")

    def generate_csv(self):
        """Generate CSV output"""
        output_file = self.output_dir / 'call_mappings.csv'

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            # Header
            writer.writerow([
                'Component', 'Component_File', 'Call_Type', 'Service_Name',
                'Method_Name', 'CSharp_Class', 'CSharp_Method', 'CSharp_File',
                'Line_Number'
            ])

            # Data rows
            for component_name, component_data in self.results['components'].items():
                component_file = component_data['file_path']

                # Direct calls
                for call in component_data['direct_calls']:
                    writer.writerow([
                        component_name, component_file, 'Direct',
                        call['service_name'], call['method_name'],
                        '', '', '', call['line_number']
                    ])

                # Indirect calls with C# mappings
                for mapping in component_data['csharp_mappings']:
                    writer.writerow([
                        component_name, component_file, 'Indirect',
                        '', mapping['angular_call'],
                        mapping['csharp_class'], mapping['csharp_method'],
                        mapping['file_path'], mapping['line_number']
                    ])

        logger.info(f"CSV output generated: {output_file}")

    def generate_html(self):
        """Generate HTML output"""
        output_file = self.output_dir / 'call_mappings.html'

        html_content = self._build_html_content()

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

        logger.info(f"HTML output generated: {output_file}")

    def _build_html_content(self) -> str:
        """Build HTML content"""
        html_parts = [
            '<!DOCTYPE html>',
            '<html lang="en">',
            '<head>',
            '<meta charset="UTF-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
            '<title>Angular to C# Call Path Mappings</title>',
            '<style>',
            self._get_html_styles(),
            '</style>',
            '</head>',
            '<body>',
            '<div class="container">',
            '<h1>Angular to C# Call Path Mappings</h1>',
            self._build_summary_section(),
            self._build_components_section(),
            '</div>',
            '<script>',
            self._get_html_scripts(),
            '</script>',
            '</body>',
            '</html>'
        ]

        return '\n'.join(html_parts)

    def _get_html_styles(self) -> str:
        """Get HTML styles"""
        return """
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { color: #333; border-bottom: 3px solid #007acc; padding-bottom: 10px; }
        h2 { color: #007acc; margin-top: 30px; }
        h3 { color: #555; margin-top: 20px; }
        .summary { background: #e8f4fd; padding: 15px; border-radius: 5px; margin: 20px 0; }
        .component { border: 1px solid #ddd; margin: 20px 0; border-radius: 5px; }
        .component-header { background: #007acc; color: white; padding: 15px; cursor: pointer; }
        .component-content { padding: 15px; display: none; }
        .call-section { margin: 15px 0; }
        .call-item { background: #f9f9f9; padding: 10px; margin: 5px 0; border-left: 4px solid #007acc; }
        .indirect-call { border-left-color: #28a745; }
        .mapping-item { background: #fff3cd; padding: 10px; margin: 5px 0; border-left: 4px solid #ffc107; }
        .file-path { font-family: monospace; font-size: 0.9em; color: #666; }
        table { width: 100%; border-collapse: collapse; margin: 10px 0; }
        th, td { padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background-color: #f2f2f2; }
        .toggle-btn { background: none; border: none; color: white; float: right; font-size: 1.2em; }
        """

    def _get_html_scripts(self) -> str:
        """Get HTML scripts"""
        return """
        function toggleComponent(element) {
            const content = element.nextElementSibling;
            const btn = element.querySelector('.toggle-btn');
            if (content.style.display === 'none' || content.style.display === '') {
                content.style.display = 'block';
                btn.textContent = '−';
            } else {
                content.style.display = 'none';
                btn.textContent = '+';
            }
        }
        """

    def _build_summary_section(self) -> str:
        """Build summary section"""
        summary = self.results['summary']
        return f"""
        <div class="summary">
            <h2>Summary</h2>
            <p><strong>Total Angular Components:</strong> {summary['total_components']}</p>
            <p><strong>Total Angular Services:</strong> {summary['total_services']}</p>
            <p><strong>Total C# Classes:</strong> {summary['total_csharp_classes']}</p>
        </div>
        """

    def _build_components_section(self) -> str:
        """Build components section"""
        parts = ['<h2>Components and Call Paths</h2>']

        for component_name, component_data in self.results['components'].items():
            parts.append(f"""
            <div class="component">
                <div class="component-header" onclick="toggleComponent(this)">
                    <strong>{html.escape(component_name)}</strong>
                    <button class="toggle-btn">+</button>
                </div>
                <div class="component-content">
                    <p class="file-path"><strong>File:</strong> {html.escape(component_data['file_path'])}</p>
                    {self._build_template_path(component_data)}
                    {self._build_direct_calls(component_data)}
                    {self._build_indirect_calls(component_data)}
                    {self._build_csharp_mappings(component_data)}
                </div>
            </div>
            """)

        return '\n'.join(parts)

    def _build_template_path(self, component_data: Dict) -> str:
        """Build template path section"""
        if component_data['template_path']:
            return f'<p class="file-path"><strong>Template:</strong> {html.escape(component_data["template_path"])}</p>'
        return ''

    def _build_direct_calls(self, component_data: Dict) -> str:
        """Build direct calls section"""
        if not component_data['direct_calls']:
            return '<div class="call-section"><h3>Direct Service Calls</h3><p>No direct calls found.</p></div>'

        parts = ['<div class="call-section"><h3>Direct Service Calls</h3>']
        for call in component_data['direct_calls']:
            parts.append(f"""
            <div class="call-item">
                <strong>{html.escape(call['service_name'])}.{html.escape(call['method_name'])}</strong>
                <br><span class="file-path">Line {call['line_number']}</span>
            </div>
            """)
        parts.append('</div>')
        return '\n'.join(parts)

    def _build_indirect_calls(self, component_data: Dict) -> str:
        """Build indirect calls section"""
        if not component_data['indirect_calls']:
            return '<div class="call-section"><h3>Indirect Calls (HTTP)</h3><p>No indirect calls found.</p></div>'

        parts = ['<div class="call-section"><h3>Indirect Calls (HTTP)</h3>']
        for call in component_data['indirect_calls']:
            parts.append(f"""
            <div class="call-item indirect-call">
                <strong>{html.escape(call['service_name'])}</strong>
                <br>→ {html.escape(call['method_name'])}
                <br><span class="file-path">Line {call['line_number']}</span>
            </div>
            """)
        parts.append('</div>')
        return '\n'.join(parts)

    def _build_csharp_mappings(self, component_data: Dict) -> str:
        """Build C# mappings section"""
        if not component_data['csharp_mappings']:
            return '<div class="call-section"><h3>C# Method Mappings</h3><p>No C# mappings found.</p></div>'

        parts = ['<div class="call-section"><h3>C# Method Mappings</h3>']
        for mapping in component_data['csharp_mappings']:
            params_str = ', '.join(mapping['parameters']) if mapping['parameters'] else 'none'
            parts.append(f"""
            <div class="mapping-item">
                <strong>{html.escape(mapping['csharp_class'])}.{html.escape(mapping['csharp_method'])}</strong>
                <br><strong>Returns:</strong> {html.escape(mapping['return_type'])}
                <br><strong>Parameters:</strong> {html.escape(params_str)}
                <br><strong>Maps to:</strong> {html.escape(mapping['angular_call'])}
                <br><span class="file-path">{html.escape(mapping['file_path'])} (Line {mapping['line_number']})</span>
            </div>
            """)
        parts.append('</div>')
        return '\n'.join(parts)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Map Angular component call paths to C# services and methods',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python angular_csharp_mapper.py --angular-path ./src/app --csharp-path ./api --output-formats json html
  python angular_csharp_mapper.py --angular-path ./frontend --csharp-path ./backend --output-formats all --include-tests
  python angular_csharp_mapper.py --angular-path ./client --csharp-path ./server --output-dir ./reports --max-depth 5
        """
    )

    parser.add_argument(
        '--angular-path',
        required=True,
        help='Path to Angular project root directory'
    )

    parser.add_argument(
        '--csharp-path',
        required=True,
        help='Path to C# project root directory'
    )

    parser.add_argument(
        '--output-formats',
        nargs='+',
        choices=['json', 'csv', 'html', 'all'],
        default=['json'],
        help='Output formats to generate (default: json)'
    )

    parser.add_argument(
        '--output-dir',
        default='./output',
        help='Output directory for generated files (default: ./output)'
    )

    parser.add_argument(
        '--max-depth',
        type=int,
        default=10,
        help='Maximum recursion depth for call path analysis (default: 10)'
    )

    parser.add_argument(
        '--include-tests',
        action='store_true',
        help='Include test files in analysis'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Validate paths
    if not os.path.exists(args.angular_path):
        logger.error(f"Angular path does not exist: {args.angular_path}")
        return 1

    if not os.path.exists(args.csharp_path):
        logger.error(f"C# path does not exist: {args.csharp_path}")
        return 1

    # Handle 'all' format option
    output_formats = args.output_formats
    if 'all' in output_formats:
        output_formats = ['json', 'csv', 'html']

    try:
        # Initialize analyzer
        analyzer = CodeAnalyzer(
            angular_path=args.angular_path,
            csharp_path=args.csharp_path,
            output_formats=output_formats,
            max_depth=args.max_depth,
            include_tests=args.include_tests
        )

        # Perform analysis
        results = analyzer.analyze()

        # Generate output
        generator = OutputGenerator(results, args.output_dir)
        generator.generate_all(output_formats)

        logger.info("Analysis completed successfully!")
        return 0

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(main())