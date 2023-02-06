# Copyright The Lightning team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from functools import partial

import numpy as np
import pytest
import torch
from scipy.special import expit as sigmoid
from scipy.special import softmax
from sklearn.metrics import roc_curve as sk_roc_curve

from torchmetrics.classification.specificity_at_sensitivity import (
    BinarySpecificityAtSensitivity,
    MulticlassSpecificityAtSensitivity,
    MultilabelSpecificityAtSensitivity,
)
from torchmetrics.functional.classification.specificity_at_sensitivity import (
    _convert_fpr_to_specificity,
    binary_specificity_at_sensitivity,
    multiclass_specificity_at_sensitivity,
    multilabel_specificity_at_sensitivity,
)
from unittests.classification.inputs import _binary_cases, _multiclass_cases, _multilabel_cases
from unittests.helpers import seed_all
from unittests.helpers.testers import NUM_CLASSES, MetricTester, inject_ignore_index, remove_ignore_index

seed_all(42)


def specificity_at_sensitivity_x_multilabel(predictions, targets, min_sensitivity):
    # get fpr, tpr and thresholds
    fpr, sensitivity, thresholds = sk_roc_curve(targets, predictions, pos_label=1.0, drop_intermediate=False)
    # check if fpr is filled with nan (All positive samples),
    # replace nan with zero tensor
    if np.isnan(fpr).all():
        fpr = np.zeros_like(thresholds)

    # convert fpr to specificity (specificity = 1 - fpr)
    specificity = _convert_fpr_to_specificity(fpr)

    # get indices where sensitivity is greater than min_sensitivity
    indices = sensitivity >= min_sensitivity

    # if no indices are found, max_spec, best_threshold = 0.0, 1e6
    if not indices.any():
        max_spec, best_threshold = 0.0, 1e6
    else:
        # redefine specificity, sensitivity and threshold tensor based on indices
        specificity, sensitivity, thresholds = specificity[indices], sensitivity[indices], thresholds[indices]

        # get argmax
        idx = np.argmax(specificity)

        # get max_spec and best_threshold
        max_spec, best_threshold = specificity[idx], thresholds[idx]

    return float(max_spec), float(best_threshold)


def _sklearn_specificity_at_sensitivity_binary(preds, target, min_sensitivity, ignore_index=None):
    preds = preds.flatten().numpy()
    target = target.flatten().numpy()
    if np.issubdtype(preds.dtype, np.floating) and not ((preds > 0) & (preds < 1)).all():
        preds = sigmoid(preds)
    target, preds = remove_ignore_index(target, preds, ignore_index)
    return specificity_at_sensitivity_x_multilabel(preds, target, min_sensitivity)


@pytest.mark.parametrize("input", (_binary_cases[1], _binary_cases[2], _binary_cases[4], _binary_cases[5]))
class TestBinarySpecificityAtSensitivity(MetricTester):
    @pytest.mark.parametrize("min_sensitivity", [0.05, 0.1, 0.3, 0.5, 0.85])
    @pytest.mark.parametrize("ignore_index", [None, -1, 0])
    @pytest.mark.parametrize("ddp", [True, False])
    def test_binary_specificity_at_sensitivity(self, input, ddp, min_sensitivity, ignore_index):
        preds, target = input
        if ignore_index is not None:
            target = inject_ignore_index(target, ignore_index)
        self.run_class_metric_test(
            ddp=ddp,
            preds=preds,
            target=target,
            metric_class=BinarySpecificityAtSensitivity,
            reference_metric=partial(
                _sklearn_specificity_at_sensitivity_binary, min_sensitivity=min_sensitivity, ignore_index=ignore_index
            ),
            metric_args={
                "min_sensitivity": min_sensitivity,
                "thresholds": None,
                "ignore_index": ignore_index,
            },
        )

    @pytest.mark.parametrize("min_sensitivity", [0.05, 0.1, 0.3, 0.5, 0.8])
    @pytest.mark.parametrize("ignore_index", [None, -1, 0])
    def test_binary_specificity_at_sensitivity_functional(self, input, min_sensitivity, ignore_index):
        preds, target = input
        if ignore_index is not None:
            target = inject_ignore_index(target, ignore_index)
        self.run_functional_metric_test(
            preds=preds,
            target=target,
            metric_functional=binary_specificity_at_sensitivity,
            reference_metric=partial(
                _sklearn_specificity_at_sensitivity_binary, min_sensitivity=min_sensitivity, ignore_index=ignore_index
            ),
            metric_args={
                "min_sensitivity": min_sensitivity,
                "thresholds": None,
                "ignore_index": ignore_index,
            },
        )

    def test_binary_specificity_at_sensitivity_differentiability(self, input):
        preds, target = input
        self.run_differentiability_test(
            preds=preds,
            target=target,
            metric_module=BinarySpecificityAtSensitivity,
            metric_functional=binary_specificity_at_sensitivity,
            metric_args={"min_sensitivity": 0.5, "thresholds": None},
        )

    @pytest.mark.parametrize("dtype", [torch.half, torch.double])
    def test_binary_specificity_at_sensitivity_dtype_cpu(self, input, dtype):
        preds, target = input
        if (preds < 0).any() and dtype == torch.half:
            pytest.xfail(reason="torch.sigmoid in metric does not support cpu + half precision")
        self.run_precision_test_cpu(
            preds=preds,
            target=target,
            metric_module=BinarySpecificityAtSensitivity,
            metric_functional=binary_specificity_at_sensitivity,
            metric_args={"min_sensitivity": 0.5, "thresholds": None},
            dtype=dtype,
        )

    @pytest.mark.skipif(not torch.cuda.is_available(), reason="test requires cuda")
    @pytest.mark.parametrize("dtype", [torch.half, torch.double])
    def test_binary_specificity_at_sensitivity_dtype_gpu(self, input, dtype):
        preds, target = input
        self.run_precision_test_gpu(
            preds=preds,
            target=target,
            metric_module=BinarySpecificityAtSensitivity,
            metric_functional=binary_specificity_at_sensitivity,
            metric_args={"min_sensitivity": 0.5, "thresholds": None},
            dtype=dtype,
        )

    @pytest.mark.parametrize("min_sensitivity", [0.05, 0.1, 0.3, 0.5, 0.8])
    def test_binary_specificity_at_sensitivity_threshold_arg(self, input, min_sensitivity):
        preds, target = input

        for pred, true in zip(preds, target):
            pred = torch.tensor(np.round(pred.numpy(), 1)) + 1e-6  # rounding will simulate binning
            r1, _ = binary_specificity_at_sensitivity(pred, true, min_sensitivity=min_sensitivity, thresholds=None)
            r2, _ = binary_specificity_at_sensitivity(
                pred, true, min_sensitivity=min_sensitivity, thresholds=torch.linspace(0, 1, 100)
            )
            assert torch.allclose(r1, r2)


def _sklearn_specificity_at_sensitivity_multiclass(preds, target, min_sensitivity, ignore_index=None):
    preds = np.moveaxis(preds.numpy(), 1, -1).reshape((-1, preds.shape[1]))
    target = target.numpy().flatten()
    if not ((preds > 0) & (preds < 1)).all():
        preds = softmax(preds, 1)
    target, preds = remove_ignore_index(target, preds, ignore_index)

    specificity, thresholds = [], []
    for i in range(NUM_CLASSES):
        target_temp = np.zeros_like(target)
        target_temp[target == i] = 1
        res = specificity_at_sensitivity_x_multilabel(preds[:, i], target_temp, min_sensitivity)
        specificity.append(res[0])
        thresholds.append(res[1])
    return specificity, thresholds


@pytest.mark.parametrize(
    "input", (_multiclass_cases[1], _multiclass_cases[2], _multiclass_cases[4], _multiclass_cases[5])
)
class TestMulticlassSpecificityAtSensitivity(MetricTester):
    @pytest.mark.parametrize("min_sensitivity", [0.05, 0.1, 0.3, 0.5, 0.8])
    @pytest.mark.parametrize("ignore_index", [None, -1, 0])
    @pytest.mark.parametrize("ddp", [True, False])
    def test_multiclass_specificity_at_sensitivity(self, input, ddp, min_sensitivity, ignore_index):
        preds, target = input
        if ignore_index is not None:
            target = inject_ignore_index(target, ignore_index)
        self.run_class_metric_test(
            ddp=ddp,
            preds=preds,
            target=target,
            metric_class=MulticlassSpecificityAtSensitivity,
            reference_metric=partial(
                _sklearn_specificity_at_sensitivity_multiclass,
                min_sensitivity=min_sensitivity,
                ignore_index=ignore_index,
            ),
            metric_args={
                "min_sensitivity": min_sensitivity,
                "thresholds": None,
                "num_classes": NUM_CLASSES,
                "ignore_index": ignore_index,
            },
        )

    @pytest.mark.parametrize("min_sensitivity", [0.05, 0.1, 0.3, 0.5, 0.8])
    @pytest.mark.parametrize("ignore_index", [None, -1, 0])
    def test_multiclass_specificity_at_sensitivity_functional(self, input, min_sensitivity, ignore_index):
        preds, target = input
        if ignore_index is not None:
            target = inject_ignore_index(target, ignore_index)
        self.run_functional_metric_test(
            preds=preds,
            target=target,
            metric_functional=multiclass_specificity_at_sensitivity,
            reference_metric=partial(
                _sklearn_specificity_at_sensitivity_multiclass,
                min_sensitivity=min_sensitivity,
                ignore_index=ignore_index,
            ),
            metric_args={
                "min_sensitivity": min_sensitivity,
                "thresholds": None,
                "num_classes": NUM_CLASSES,
                "ignore_index": ignore_index,
            },
        )

    def test_multiclass_specificity_at_sensitivity_differentiability(self, input):
        preds, target = input
        self.run_differentiability_test(
            preds=preds,
            target=target,
            metric_module=MulticlassSpecificityAtSensitivity,
            metric_functional=multiclass_specificity_at_sensitivity,
            metric_args={"min_sensitivity": 0.5, "thresholds": None, "num_classes": NUM_CLASSES},
        )

    @pytest.mark.parametrize("dtype", [torch.half, torch.double])
    def test_multiclass_specificity_at_sensitivity_dtype_cpu(self, input, dtype):
        preds, target = input
        if dtype == torch.half and not ((preds > 0) & (preds < 1)).all():
            pytest.xfail(reason="half support for torch.softmax on cpu not implemented")
        self.run_precision_test_cpu(
            preds=preds,
            target=target,
            metric_module=MulticlassSpecificityAtSensitivity,
            metric_functional=multiclass_specificity_at_sensitivity,
            metric_args={"min_sensitivity": 0.5, "thresholds": None, "num_classes": NUM_CLASSES},
            dtype=dtype,
        )

    @pytest.mark.skipif(not torch.cuda.is_available(), reason="test requires cuda")
    @pytest.mark.parametrize("dtype", [torch.half, torch.double])
    def test_multiclass_specificity_at_sensitivity_dtype_gpu(self, input, dtype):
        preds, target = input
        self.run_precision_test_gpu(
            preds=preds,
            target=target,
            metric_module=MulticlassSpecificityAtSensitivity,
            metric_functional=multiclass_specificity_at_sensitivity,
            metric_args={"min_sensitivity": 0.5, "thresholds": None, "num_classes": NUM_CLASSES},
            dtype=dtype,
        )

    @pytest.mark.parametrize("min_sensitivity", [0.05, 0.1, 0.3, 0.5, 0.8])
    def test_multiclass_specificity_at_sensitivity_threshold_arg(self, input, min_sensitivity):
        preds, target = input
        if (preds < 0).any():
            preds = preds.softmax(dim=-1)
        for pred, true in zip(preds, target):
            pred = torch.tensor(np.round(pred.detach().numpy(), 1)) + 1e-6  # rounding will simulate binning
            r1, _ = multiclass_specificity_at_sensitivity(
                pred, true, num_classes=NUM_CLASSES, min_sensitivity=min_sensitivity, thresholds=None
            )
            r2, _ = multiclass_specificity_at_sensitivity(
                pred,
                true,
                num_classes=NUM_CLASSES,
                min_sensitivity=min_sensitivity,
                thresholds=torch.linspace(0, 1, 100),
            )
            assert all(torch.allclose(r1[i], r2[i]) for i in range(len(r1)))


def _sklearn_specificity_at_sensitivity_multilabel(preds, target, min_sensitivity, ignore_index=None):
    specificity, thresholds = [], []
    for i in range(NUM_CLASSES):
        res = _sklearn_specificity_at_sensitivity_binary(preds[:, i], target[:, i], min_sensitivity, ignore_index)
        specificity.append(res[0])
        thresholds.append(res[1])
    return specificity, thresholds


@pytest.mark.parametrize(
    "input", (_multilabel_cases[1], _multilabel_cases[2], _multilabel_cases[4], _multilabel_cases[5])
)
class TestMultilabelSpecificityAtSensitivity(MetricTester):
    @pytest.mark.parametrize("min_sensitivity", [0.05, 0.1, 0.3, 0.5, 0.8])
    @pytest.mark.parametrize("ignore_index", [None, -1, 0])
    @pytest.mark.parametrize("ddp", [True, False])
    def test_multilabel_specificity_at_sensitivity(self, input, ddp, min_sensitivity, ignore_index):
        preds, target = input
        if ignore_index is not None:
            target = inject_ignore_index(target, ignore_index)
        self.run_class_metric_test(
            ddp=ddp,
            preds=preds,
            target=target,
            metric_class=MultilabelSpecificityAtSensitivity,
            reference_metric=partial(
                _sklearn_specificity_at_sensitivity_multilabel,
                min_sensitivity=min_sensitivity,
                ignore_index=ignore_index,
            ),
            metric_args={
                "min_sensitivity": min_sensitivity,
                "thresholds": None,
                "num_labels": NUM_CLASSES,
                "ignore_index": ignore_index,
            },
        )

    @pytest.mark.parametrize("min_sensitivity", [0.05, 0.1, 0.3, 0.5, 0.8])
    @pytest.mark.parametrize("ignore_index", [None, -1, 0])
    def test_multilabel_specificity_at_sensitivity_functional(self, input, min_sensitivity, ignore_index):
        preds, target = input
        if ignore_index is not None:
            target = inject_ignore_index(target, ignore_index)
        self.run_functional_metric_test(
            preds=preds,
            target=target,
            metric_functional=multilabel_specificity_at_sensitivity,
            reference_metric=partial(
                _sklearn_specificity_at_sensitivity_multilabel,
                min_sensitivity=min_sensitivity,
                ignore_index=ignore_index,
            ),
            metric_args={
                "min_sensitivity": min_sensitivity,
                "thresholds": None,
                "num_labels": NUM_CLASSES,
                "ignore_index": ignore_index,
            },
        )

    def test_multiclass_specificity_at_sensitivity_differentiability(self, input):
        preds, target = input
        self.run_differentiability_test(
            preds=preds,
            target=target,
            metric_module=MultilabelSpecificityAtSensitivity,
            metric_functional=multilabel_specificity_at_sensitivity,
            metric_args={"min_sensitivity": 0.5, "thresholds": None, "num_labels": NUM_CLASSES},
        )

    @pytest.mark.parametrize("dtype", [torch.half, torch.double])
    def test_multilabel_specificity_at_sensitivity_dtype_cpu(self, input, dtype):
        preds, target = input
        if dtype == torch.half and not ((preds > 0) & (preds < 1)).all():
            pytest.xfail(reason="half support for torch.softmax on cpu not implemented")
        self.run_precision_test_cpu(
            preds=preds,
            target=target,
            metric_module=MultilabelSpecificityAtSensitivity,
            metric_functional=multilabel_specificity_at_sensitivity,
            metric_args={"min_sensitivity": 0.5, "thresholds": None, "num_labels": NUM_CLASSES},
            dtype=dtype,
        )

    @pytest.mark.skipif(not torch.cuda.is_available(), reason="test requires cuda")
    @pytest.mark.parametrize("dtype", [torch.half, torch.double])
    def test_multiclass_specificity_at_sensitivity_dtype_gpu(self, input, dtype):
        preds, target = input
        self.run_precision_test_gpu(
            preds=preds,
            target=target,
            metric_module=MultilabelSpecificityAtSensitivity,
            metric_functional=multilabel_specificity_at_sensitivity,
            metric_args={"min_sensitivity": 0.5, "thresholds": None, "num_labels": NUM_CLASSES},
            dtype=dtype,
        )

    @pytest.mark.parametrize("min_sensitivity", [0.05, 0.1, 0.3, 0.5, 0.8])
    def test_multilabel_specificity_at_sensitivity_threshold_arg(self, input, min_sensitivity):
        preds, target = input
        if (preds < 0).any():
            preds = sigmoid(preds)
        for pred, true in zip(preds, target):
            pred = torch.tensor(np.round(pred.detach().numpy(), 1)) + 1e-6  # rounding will simulate binning
            r1, _ = multilabel_specificity_at_sensitivity(
                pred, true, num_labels=NUM_CLASSES, min_sensitivity=min_sensitivity, thresholds=None
            )
            r2, _ = multilabel_specificity_at_sensitivity(
                pred,
                true,
                num_labels=NUM_CLASSES,
                min_sensitivity=min_sensitivity,
                thresholds=torch.linspace(0, 1, 100),
            )
            assert all(torch.allclose(r1[i], r2[i]) for i in range(len(r1)))


@pytest.mark.parametrize(
    "metric",
    [
        BinarySpecificityAtSensitivity,
        partial(MulticlassSpecificityAtSensitivity, num_classes=NUM_CLASSES),
        partial(MultilabelSpecificityAtSensitivity, num_labels=NUM_CLASSES),
    ],
)
@pytest.mark.parametrize("thresholds", [None, 100, [0.3, 0.5, 0.7, 0.9], torch.linspace(0, 1, 10)])
def test_valid_input_thresholds(metric, thresholds):
    """test valid formats of the threshold argument."""
    with pytest.warns(None) as record:
        metric(min_sensitivity=0.5, thresholds=thresholds)
    assert len(record) == 0