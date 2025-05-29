#!/usr/bin/env python3
"""
Angular to C# Call Path Mapper
Maps application call paths from Angular screens to C# services and underlying classes/methods.
Provides both direct and indirect paths by screen.
"""

import os
import re
import json
import ast
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, field
from collections import defaultdict, deque


@dataclass
class CallPath:
    """Represents a call path from Angular to C#"""
    screen: str
    angular_component: str
    angular_service: str
    api_endpoint: str
    csharp_controller: str
    csharp_method: str
    csharp_services: List[str] = field(default_factory=list)
    underlying_methods: List[str] = field(default_factory=list)
    path_type: str = "direct"  # "direct" or "indirect"
    depth: int = 0


@dataclass
class AngularComponent:
    """Angular component information"""
    name: str
    file_path: str
    services: List[str] = field(default_factory=list)
    api_calls: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)


@dataclass
class CSharpController:
    """C# controller information"""
    name: str
    file_path: str
    methods: Dict[str, List[str]] = field(default_factory=dict)  # method -> services called
    endpoints: Dict[str, str] = field(default_factory=dict)  # endpoint -> method


@dataclass
class CSharpService:
    """C# service information"""
    name: str
    file_path: str
    methods: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)


class AngularAnalyzer:
    """Analyzes Angular TypeScript files"""

    def __init__(self, angular_path: str):
        self.angular_path = Path(angular_path)
        self.components: Dict[str, AngularComponent] = {}
        self.services: Dict[str, List[str]] = {}  # service -> methods

    def analyze(self):
        """Analyze Angular project structure"""
        self._find_components()
        self._find_services()
        self._analyze_component_dependencies()

    def _find_components(self):
        """Find all Angular components"""
        for ts_file in self.angular_path.rglob("*.component.ts"):
            self._parse_component_file(ts_file)

    def _find_services(self):
        """Find all Angular services"""
        for ts_file in self.angular_path.rglob("*.service.ts"):
            self._parse_service_file(ts_file)

    def _parse_component_file(self, file_path: Path):
        """Parse Angular component file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Extract component name
            component_match = re.search(r'export\s+class\s+(\w+Component)', content)
            if not component_match:
                return

            component_name = component_match.group(1)
            component = AngularComponent(name=component_name, file_path=str(file_path))

            # Find injected services
            constructor_match = re.search(r'constructor\s*\([^)]*\)', content, re.DOTALL)
            if constructor_match:
                constructor = constructor_match.group(0)
                service_matches = re.findall(r'private\s+\w+:\s*(\w+Service)', constructor)
                component.services.extend(service_matches)

            # Find API calls (HTTP calls)
            api_patterns = [
                r'this\.http\.(get|post|put|delete)\s*\(\s*[\'"`]([^\'"`]+)[\'"`]',
                r'this\.\w+\.(get|post|put|delete)\s*\(\s*[\'"`]([^\'"`]+)[\'"`]',
                r'this\.\w+\.(\w+)\s*\(',  # Service method calls
            ]

            for pattern in api_patterns:
                matches = re.findall(pattern, content)
                for match in matches:
                    if len(match) == 2:
                        component.api_calls.append(f"{match[0]}:{match[1]}")
                    else:
                        component.api_calls.append(match[0] if isinstance(match, tuple) else match)

            self.components[component_name] = component

        except Exception as e:
            print(f"Error parsing component {file_path}: {e}")

    def _parse_service_file(self, file_path: Path):
        """Parse Angular service file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Extract service name
            service_match = re.search(r'export\s+class\s+(\w+Service)', content)
            if not service_match:
                return

            service_name = service_match.group(1)

            # Find methods
            method_matches = re.findall(r'(\w+)\s*\([^)]*\)\s*:', content)
            self.services[service_name] = method_matches

        except Exception as e:
            print(f"Error parsing service {file_path}: {e}")

    def _analyze_component_dependencies(self):
        """Analyze component dependencies and service calls"""
        for component in self.components.values():
            try:
                with open(component.file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Find service method calls
                for service in component.services:
                    service_calls = re.findall(rf'this\.(\w+)\.(\w+)\s*\(', content)
                    component.dependencies.extend([f"{call[0]}.{call[1]}" for call in service_calls])

            except Exception as e:
                print(f"Error analyzing dependencies for {component.name}: {e}")


class CSharpAnalyzer:
    """Analyzes C# files"""

    def __init__(self, csharp_path: str):
        self.csharp_path = Path(csharp_path)
        self.controllers: Dict[str, CSharpController] = {}
        self.services: Dict[str, CSharpService] = {}

    def analyze(self):
        """Analyze C# project structure"""
        self._find_controllers()
        self._find_services()
        self._analyze_dependencies()

    def _find_controllers(self):
        """Find all C# controllers"""
        for cs_file in self.csharp_path.rglob("*Controller.cs"):
            self._parse_controller_file(cs_file)

    def _find_services(self):
        """Find all C# services"""
        service_patterns = ["*Service.cs", "*Repository.cs", "*Manager.cs"]
        for pattern in service_patterns:
            for cs_file in self.csharp_path.rglob(pattern):
                self._parse_service_file(cs_file)

    def _parse_controller_file(self, file_path: Path):
        """Parse C# controller file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Extract controller name
            controller_match = re.search(r'public\s+class\s+(\w+Controller)', content)
            if not controller_match:
                return

            controller_name = controller_match.group(1)
            controller = CSharpController(name=controller_name, file_path=str(file_path))

            # Find HTTP endpoints and methods
            endpoint_patterns = [
                r'\[Http(Get|Post|Put|Delete)\s*\(\s*"([^"]+)"\s*\)\]\s*public\s+\w+\s+(\w+)\s*\(',
                r'\[Route\s*\(\s*"([^"]+)"\s*\)\]\s*public\s+\w+\s+(\w+)\s*\(',
            ]

            for pattern in endpoint_patterns:
                matches = re.findall(pattern, content, re.MULTILINE | re.DOTALL)
                for match in matches:
                    if len(match) == 3:  # HTTP method with route and method name
                        route = match[1]
                        method_name = match[2]
                        controller.endpoints[route] = method_name
                    elif len(match) == 2:  # Route with method name
                        route = match[0]
                        method_name = match[1]
                        controller.endpoints[route] = method_name

            # Find method dependencies (service calls)
            method_matches = re.findall(r'public\s+\w+\s+(\w+)\s*\([^)]*\)\s*{([^}]*)}', content, re.DOTALL)
            for method_name, method_body in method_matches:
                service_calls = re.findall(r'(\w+)\.(\w+)\s*\(', method_body)
                controller.methods[method_name] = [f"{call[0]}.{call[1]}" for call in service_calls]

            self.controllers[controller_name] = controller

        except Exception as e:
            print(f"Error parsing controller {file_path}: {e}")

    def _parse_service_file(self, file_path: Path):
        """Parse C# service file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Extract service name
            class_match = re.search(r'public\s+class\s+(\w+(?:Service|Repository|Manager))', content)
            if not class_match:
                return

            service_name = class_match.group(1)
            service = CSharpService(name=service_name, file_path=str(file_path))

            # Find methods
            method_matches = re.findall(r'public\s+\w+\s+(\w+)\s*\([^)]*\)', content)
            service.methods = method_matches

            # Find dependencies (constructor injection)
            constructor_match = re.search(r'public\s+' + service_name + r'\s*\([^)]*\)', content)
            if constructor_match:
                constructor = constructor_match.group(0)
                dep_matches = re.findall(r'I(\w+(?:Service|Repository|Manager))\s+\w+', constructor)
                service.dependencies = dep_matches

            self.services[service_name] = service

        except Exception as e:
            print(f"Error parsing service {file_path}: {e}")

    def _analyze_dependencies(self):
        """Analyze service dependencies"""
        # This would involve more complex analysis of method calls within services
        pass


class CallPathMapper:
    """Maps call paths from Angular to C#"""

    def __init__(self, angular_analyzer: AngularAnalyzer, csharp_analyzer: CSharpAnalyzer):
        self.angular_analyzer = angular_analyzer
        self.csharp_analyzer = csharp_analyzer
        self.call_paths: List[CallPath] = []

    def map_paths(self) -> List[CallPath]:
        """Map all call paths from Angular screens to C# services"""
        self.call_paths = []

        for component_name, component in self.angular_analyzer.components.items():
            self._map_component_paths(component)

        return self.call_paths

    def _map_component_paths(self, component: AngularComponent):
        """Map paths for a specific Angular component"""
        # Direct paths from API calls
        for api_call in component.api_calls:
            self._trace_api_call(component, api_call)

        # Indirect paths through service dependencies
        for dependency in component.dependencies:
            self._trace_service_dependency(component, dependency, depth=1)

    def _trace_api_call(self, component: AngularComponent, api_call: str):
        """Trace a direct API call to C# controller"""
        if ':' in api_call:
            method, endpoint = api_call.split(':', 1)
        else:
            method, endpoint = 'unknown', api_call

        # Find matching controller endpoint
        for controller_name, controller in self.csharp_analyzer.controllers.items():
            for route, controller_method in controller.endpoints.items():
                if self._match_endpoint(endpoint, route):
                    call_path = CallPath(
                        screen=component.name,
                        angular_component=component.name,
                        angular_service="HttpClient",
                        api_endpoint=endpoint,
                        csharp_controller=controller_name,
                        csharp_method=controller_method,
                        path_type="direct"
                    )

                    # Find underlying service calls
                    if controller_method in controller.methods:
                        call_path.csharp_services = controller.methods[controller_method]
                        call_path.underlying_methods = self._get_underlying_methods(
                            controller.methods[controller_method]
                        )

                    self.call_paths.append(call_path)

    def _trace_service_dependency(self, component: AngularComponent, dependency: str, depth: int):
        """Trace indirect service dependencies"""
        if depth > 5:  # Prevent infinite recursion
            return

        # This would trace through Angular services to find eventual API calls
        # Implementation would depend on the specific service structure
        pass

    def _match_endpoint(self, angular_endpoint: str, csharp_route: str) -> bool:
        """Check if Angular endpoint matches C# route"""
        # Simple matching - could be enhanced with parameter matching
        angular_clean = angular_endpoint.strip('/').lower()
        csharp_clean = csharp_route.strip('/').lower()

        # Remove parameter placeholders for basic matching
        csharp_clean = re.sub(r'{[^}]+}', '*', csharp_clean)
        angular_clean = re.sub(r'/\d+', '/*', angular_clean)

        return angular_clean in csharp_clean or csharp_clean in angular_clean

    def _get_underlying_methods(self, service_calls: List[str]) -> List[str]:
        """Get underlying methods called by services"""
        underlying = []

        for call in service_calls:
            if '.' in call:
                service, method = call.split('.', 1)
                # Find the service and trace its dependencies
                for service_name, service_obj in self.csharp_analyzer.services.items():
                    if service.lower() in service_name.lower():
                        underlying.append(f"{service_name}.{method}")
                        # Could recursively trace further dependencies

        return underlying

    def get_paths_by_screen(self) -> Dict[str, List[CallPath]]:
        """Group call paths by screen/component"""
        paths_by_screen = defaultdict(list)

        for path in self.call_paths:
            paths_by_screen[path.screen].append(path)

        return dict(paths_by_screen)

    def export_to_json(self, output_file: str):
        """Export call paths to JSON file"""
        paths_data = []

        for path in self.call_paths:
            paths_data.append({
                'screen': path.screen,
                'angular_component': path.angular_component,
                'angular_service': path.angular_service,
                'api_endpoint': path.api_endpoint,
                'csharp_controller': path.csharp_controller,
                'csharp_method': path.csharp_method,
                'csharp_services': path.csharp_services,
                'underlying_methods': path.underlying_methods,
                'path_type': path.path_type,
                'depth': path.depth
            })

        with open(output_file, 'w') as f:
            json.dump(paths_data, f, indent=2)

    def print_summary(self):
        """Print a summary of mapped paths"""
        paths_by_screen = self.get_paths_by_screen()

        print("=== CALL PATH MAPPING SUMMARY ===\n")

        for screen, paths in paths_by_screen.items():
            print(f"SCREEN: {screen}")
            print("-" * 50)

            direct_paths = [p for p in paths if p.path_type == "direct"]
            indirect_paths = [p for p in paths if p.path_type == "indirect"]

            if direct_paths:
                print("  DIRECT PATHS:")
                for path in direct_paths:
                    print(f"    {path.angular_component} -> {path.api_endpoint}")
                    print(f"      -> {path.csharp_controller}.{path.csharp_method}")
                    if path.csharp_services:
                        print(f"      -> Services: {', '.join(path.csharp_services)}")
                    if path.underlying_methods:
                        print(f"      -> Methods: {', '.join(path.underlying_methods)}")
                    print()

            if indirect_paths:
                print("  INDIRECT PATHS:")
                for path in indirect_paths:
                    print(f"    {path.angular_component} -> {path.angular_service}")
                    print(f"      -> {path.csharp_controller}.{path.csharp_method}")
                    print()

            print()


def main():
    """Main function to run the call path mapper"""
    # Configuration
    angular_path = input("Enter Angular project path: ").strip() or "./angular-app"
    csharp_path = input("Enter C# project path: ").strip() or "./csharp-api"
    output_file = input("Enter output JSON file path: ").strip() or "call_paths.json"

    print(f"\nAnalyzing Angular project at: {angular_path}")
    print(f"Analyzing C# project at: {csharp_path}")
    print(f"Output will be saved to: {output_file}\n")

    # Initialize analyzers
    angular_analyzer = AngularAnalyzer(angular_path)
    csharp_analyzer = CSharpAnalyzer(csharp_path)

    # Analyze projects
    print("Analyzing Angular project...")
    angular_analyzer.analyze()
    print(f"Found {len(angular_analyzer.components)} components and {len(angular_analyzer.services)} services")

    print("Analyzing C# project...")
    csharp_analyzer.analyze()
    print(f"Found {len(csharp_analyzer.controllers)} controllers and {len(csharp_analyzer.services)} services")

    # Map call paths
    print("Mapping call paths...")
    mapper = CallPathMapper(angular_analyzer, csharp_analyzer)
    call_paths = mapper.map_paths()

    print(f"Found {len(call_paths)} call paths")

    # Export results
    mapper.export_to_json(output_file)
    print(f"Results exported to {output_file}")

    # Print summary
    mapper.print_summary()


if __name__ == "__main__":
    main()