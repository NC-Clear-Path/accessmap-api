import copy
import geojson
import math
import networkx as nx
from shapely.geometry import mapping, LineString
from accessmapapi.graph import query
from accessmapapi.utils import cut
from . import costs
from . import directions


def dijkstra(origin, destination, G, sindex,
             cost_fun_gen=costs.cost_fun_generator, cost_kwargs=None,
             only_valid=True):
    '''Process a routing request, returning a Mapbox-compatible routing JSON
    object.

    :param origin: lat-lon of starting location.
    :type origin: list of coordinates
    :param destination: lat-lon of ending location.
    :type destination: list of coordinates
    :param cost_fun_gen: Function that generates a cost function given the
           info from `cost_kwargs`.
    :type cost_fun_gen: callable
    :param cost_kwargs: keyword arguments to pass to the cost function.
    :type cost_kwargs: dict

    '''
    # Query the start and end points for viable features
    cost_fun = costs.cost_fun_generator(**cost_kwargs)
    origins = query.closest_valid_startpoints(G, sindex, origin.x, origin.y,
                                              100, cost_fun)
    destinations = query.closest_valid_startpoints(G, sindex, destination.x,
                                                   destination.y, 100,
                                                   cost_fun, dest=True)

    if origins is None:
        if destinations is None:
            return {
                'code': 'BothFarAway',
                'waypoints': [],
                'routes': []
            }
        else:
            return {
                'code': 'OriginFarAway',
                'waypoints': [],
                'routes': []
            }
    else:
        if destinations is None:
            return {
                'code': 'DestinationFarAway',
                'waypoints': [],
                'routes': []
            }

    paths_data = []
    for o in origins:
        for d in destinations:
            if o == d:
                # Start and end points are the same - no route!
                continue
            path_data = geojson.FeatureCollection([])

            try:
                # TODO: consider just reimplementing custom dijkstra so that
                # temporary edges/costing can be used and more custom behavior
                # can be encoded (such as infinite costs). NetworkX
                # implementation is under networkx>algorithms>shortest_paths>
                # weighted: _dijkstra_multisource
                total_cost, path = nx.single_source_dijkstra(G, o['node'],
                                                             d['node'],
                                                             weight=cost_fun)
            except nx.NetworkXNoPath:
                continue

            if 'initial_edge' in o:
                feature1 = edge_to_feature(o['initial_edge'],
                                           o['initial_cost'])
                path_data['features'].append(feature1)

            for u, v in zip(path[:-1], path[1:]):
                edge = G[u][v]
                cost = cost_fun(u, v, edge)
                reverse = edge['from'] != u
                feature = edge_to_feature(edge, cost, reverse)
                path_data['features'].append(feature)

            if 'initial_edge' in d:
                feature2 = edge_to_feature(d['initial_edge'],
                                           d['initial_cost'])
                path_data['features'].append(feature2)

            total_cost += o['initial_cost']
            total_cost += d['initial_cost']

            path_data['total_cost'] = total_cost
            paths_data.append(path_data)

    # Special case: if it's on the same path, consider the same-path route
    if 'original_edge' in origins[0] and 'original_edge' in destinations[0]:
        if origins[0]['original_edge'] == destinations[0]['original_edge']:
            o = origins[0]
            d = destinations[0]
            # The start and end are on the same path. Consider the on-edge
            # path.
            between = copy.deepcopy(o['original_edge'])

            o_diff = o['initial_edge']['length'] - edge['length']
            d_diff = d['initial_edge']['length'] - edge['length']
            between['length'] = between['length'] - o_diff - d_diff

            o_along = between['geometry'].project(o['point'])
            d_along = between['geometry'].project(d['point'])
            first, second = reversed(sorted([o_along, d_along]))
            line = between['geometry']
            line, _ = cut(between['geometry'], first)
            _, line = cut(line, second)

            if o_along > d_along:
                # Going in the reverse direction
                coords = reversed(line.coords)
                line = LineString(coords)
                between['incline'] = -1.0 * between['incline']

            between['geometry'] = line

            path_data = geojson.FeatureCollection([])
            cost = cost_fun(-1, -2, between)
            path_data['total_cost'] = cost
            feature = edge_to_feature(between, cost)
            path_data.features.append(feature)
            paths_data.append(path_data)

    if paths_data:
        best_path = sorted(paths_data, key=lambda x: x['total_cost'])[0]
    else:
        return {
            'code': 'NoRoute',
            'waypoints': [],
            'routes': []
        }

    if best_path['total_cost'] == math.inf:
        # Note valid paths were found.
        # TODO: extract something more informative so users know what params
        # to relax.
        return {
            'code': 'NoRoute',
            'waypoints': [],
            'routes': []
        }

    # Start at first point
    segments = geojson.FeatureCollection([])
    coords = [best_path['features'][0]['geometry']['coordinates'][0]]
    for feature in best_path['features']:
        segments['features'].append(feature)
        coords += feature['geometry']['coordinates'][1:]

    # Produce the response
    # TODO: return JSON directions similar to Mapbox or OSRM so e.g.
    # leaflet-routing-machine can be used
    '''
    Format:
    JSON hash with:
        origin: geoJSON Feature with Point geometry for start point of route
        destination: geoJSON Feature with Point geometry for end point of route
        waypoints: array of geoJSON Feature Points
        routes: array of routes in descending order (just 1 for now):
            summary: A short, human-readable summary of the route. DISABLED.
            geometry: geoJSON LineString of the route (OSRM/Mapbox use
                      polyline, often)
            steps: optional array of route steps (directions/maneuvers).
                   (NOT IMPLEMENTED YET)
                way_name: way along which travel proceeds
                direction: cardinal direction (e.g. N, SW, E, etc)
                maneuver: JSON object representing the maneuver
                    No spec yet, but will mirror driving directions:
                        type: string of type of maneuver (short) e.g. cross
                              left/right
                        location: geoJSON Point geometry of maneuver location
                        instruction: e.g.
                            turn left and cross <street> on near side


    TODO:
        Add these to routes:
            distance: distance of route in meters
        Add these to steps:
            distance: distance from step maneuver to next step
            heading: what is this for? Drawing an arrow maybe?
    '''
    origin_feature = geojson.Feature()
    origin_feature['geometry'] = mapping(origin)
    destination_feature = geojson.Feature()
    destination_feature['geometry'] = mapping(destination)

    waypoints_feature_list = []
    for waypoint in [origin, destination]:
        waypoint_feature = {
            'type': 'Feature',
            'geometry': {
              'type': 'Point',
              'coordinates': waypoint.coords[0]
            },
            'properties': {}
        }
        waypoints_feature_list.append(waypoint_feature)

    # TODO: here's where to add alternative routes once we have them
    routes = []
    route = {}
    route['geometry'] = {
        'type': 'LineString',
        'coordinates': coords
    }

    # Add annotated segment GeoJSON FeatureCollection
    route['segments'] = segments

    # Extract steps information
    sidewalk_track = ['length', 'street_name', 'side', 'surface']
    crossing_track = ['curbramps', 'length', 'marked']
    elevator_track = ['indoor', 'length', 'via']
    steps_data = directions.path_to_directions(best_path, sidewalk_track,
                                               crossing_track, elevator_track)

    # TODO: Add steps!
    route['legs'] = []
    route['legs'].append(steps_data)
    route['summary'] = ''
    route['duration'] = int(best_path['total_cost'])
    total_distance = 0
    for feature in best_path['features']:
        total_distance += feature['properties']['length']
    route['distance'] = round(total_distance, 1)
    route['total_cost'] = round(best_path['total_cost'], 2)

    routes.append(route)

    route_response = {}
    route_response['origin'] = origin_feature
    route_response['destination'] = destination_feature
    route_response['waypoints'] = waypoints_feature_list
    route_response['routes'] = routes
    route_response['code'] = 'Ok'

    return route_response


def edge_to_feature(edge, cost, reverse=False):
    feature = geojson.Feature()

    # Prevent editing of original edge
    edge = copy.deepcopy(edge)

    if reverse:
        coords = list(reversed(edge['geometry'].coords))
        edge['geometry'].coords = coords

        if 'incline' in edge:
            edge['incline'] = -1.0 * edge['incline']

    feature['geometry'] = mapping(edge['geometry'])

    edge['cost'] = cost

    edge.pop('from')
    edge.pop('to')
    edge.pop('geometry')

    feature['properties'] = edge

    return feature
