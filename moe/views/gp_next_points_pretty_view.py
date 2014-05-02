# -*- coding: utf-8 -*-
"""A class to encapsulate 'pretty' views for gp_next_points_* endpoints.

Include:
    1. Request and response schemas
    2. Class that extends GpPrettyView for next_points optimizers
"""
import colander

import moe.build.GPP as C_GP
from moe.optimal_learning.EPI.src.python.cpp_wrappers.optimization import GradientDescentParameters, GradientDescentOptimizer, NullOptimizer
from moe.views.gp_pretty_view import GpPrettyView
from moe.views.schemas import GpInfo, EiOptimizationParameters, ListOfPointsInDomain, ListOfExpectedImprovements
from moe.views.utils import _make_gp_from_gp_info


class GpNextPointsRequest(colander.MappingSchema):

    """A gp_next_points_* request colander schema.

    **Required fields**

        :gp_info: a moe.views.schemas.GpInfo object of historical data

    **Optional fields**

        :num_samples_to_generate: number of next points to generate (default: 1)
        :ei_optimization_parameters: moe.views.schemas.EiOptimizationParameters() object containing optimization parameters (default: moe.optimal_learning.EPI.src.python.constant.default_ei_optimization_parameters)

    **Example Request**

    .. sourcecode:: http

        Content-Type: text/javascript

        {
            'num_samples_to_generate': 1,
            'gp_info': {
                'points_sampled': [
                        {'value_var': 0.01, 'value': 0.1, 'point': [0.0]},
                        {'value_var': 0.01, 'value': 0.2, 'point': [1.0]}
                    ],
                'domain': [
                    [0, 1],
                    ]
                },
            },
        }

    """

    num_samples_to_generate = colander.SchemaNode(
            colander.Int(),
            validator=colander.Range(min=1),
            )
    gp_info = GpInfo()
    ei_optimization_parameters = EiOptimizationParameters(
            missing=EiOptimizationParameters().deserialize({})
            )


class GpNextPointsResponse(colander.MappingSchema):

    """A gp_next_points_* response colander schema.

    **Output fields**

        :endpoint: the endpoint that was called
        :points_to_sample: list of points in the domain to sample next (moe.views.schemas.ListOfPointsInDomain)
        :expected_improvement: list of EI of points in points_to_sample (moe.views.schemas.ListOfExpectedImprovements)

    **Example Response**

    .. sourcecode:: http

        {
            "endpoint":"gp_ei",
            "points_to_sample": [["0.478332304526"]],
            "expected_improvement": ["0.443478498868"],
        }

    """

    endpoint = colander.SchemaNode(colander.String())
    points_to_sample = ListOfPointsInDomain()
    expected_improvement = ListOfExpectedImprovements()


class GpNextPointsPrettyView(GpPrettyView):

    """A class to encapsulate 'pretty' gp_next_points_* views.

    Extends GpPrettyView with:
        1. GP generation from params
        2. Converting params into a C++ consumable set of optimization parameters
        3. A method (compute_next_points_to_sample_response) for computing the next best points to sample from a GP

    """

    request_schema = GpNextPointsRequest()
    response_schema = GpNextPointsResponse()

    pretty_default_request = {
            "num_samples_to_generate": 1,
            "gp_info": GpPrettyView.pretty_default_gp_info,
            }

    def compute_next_points_to_sample_response(self, params, optimization_method_name, route_name, *args, **kwargs):
        """Compute the next points to sample (and their expected improvement) using optimization_method_name from params in the request."""
        num_samples_to_generate = params.get('num_samples_to_generate')

        GP = self.make_gp(params)
        optimizer_type, num_random_samples, optimization_parameters, domain_type = self.get_optimization_parameters_cpp(params)

        optimization_method = getattr(GP, optimization_method_name)

        next_points = optimization_method(
                optimizer_type,
                optimization_parameters,
                domain_type,
                num_random_samples,
                num_samples_to_generate,
                *args,
                **kwargs
                )
        expected_improvement = GP.evaluate_expected_improvement_at_point_list(next_points)

        return self.form_response({
                'endpoint': route_name,
                'points_to_sample': next_points.tolist(),
                'expected_improvement': expected_improvement.tolist(),
                })

    @staticmethod
    def make_gp(params):
        """Create a GP object from params."""
        gp_info = params.get('gp_info')
        return _make_gp_from_gp_info(gp_info)

    @staticmethod
    def get_optimization_parameters_cpp(params):
        """Figure out which cpp_wrappers.* objects to construct from params."""
        ei_optimization_parameters = params.get('ei_optimization_parameters')

        # TODO(eliu): clean this up!
        # TODO(sclark): should this endpoint also support 'dumb' search optimization?

        # TODO(eliu): domain_type should passed as part of the domain; this is a hack until I
        # refactor these calls to use the new interface
        num_random_samples = ei_optimization_parameters.get('num_random_samples')
        domain_type = C_GP.DomainTypes.tensor_product
        if ei_optimization_parameters.get('optimizer_type') == 'gradient_descent':
            optimizer = GradientDescentOptimizer
            # Note: num_random_samples only has meaning when computing more than 1 points_to_sample simultaneously
            optimization_parameters = GradientDescentParameters(
                ei_optimization_parameters.get('num_multistarts'),
                ei_optimization_parameters.get('gd_iterations'),
                ei_optimization_parameters.get('max_num_restarts'),
                ei_optimization_parameters.get('gamma'),
                ei_optimization_parameters.get('pre_mult'),
                ei_optimization_parameters.get('max_relative_change'),
                ei_optimization_parameters.get('tolerance'),
            )
        else:
            # null optimization (dumb search)
            optimizer = NullOptimizer
            num_random_samples = ei_optimization_parameters.get('num_random_samples'),
            optimization_parameters = None

        return optimizer, num_random_samples, optimization_parameters, domain_type