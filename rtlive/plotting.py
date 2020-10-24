import datetime
import locale
import numpy
import matplotlib
from matplotlib import pyplot, cm
import pandas
import textwrap
import typing

import arviz
import pymc3

from . import assumptions
from . import model
from . import preprocessing


def plot_vlines(
    ax: matplotlib.axes.Axes,
    vlines: preprocessing.NamedDates,
    alignment: str,
) -> None:
    """ Helper function for marking special events with labeled vertical lines.

    Parameters
    ----------
    ax : matplotlib.axes.Axes
        the subplot to draw into
    vlines : dict of { datetime : label }
        the dates and labels for the lines
    alignment : str
        one of { "top", "bottom" }
    """
    ymin, ymax = ax.get_ylim()
    xmin, xmax = ax.get_xlim()
    for x, label in vlines.items():
        if xmin <= ax.xaxis.convert_xunits(x) <= xmax:
            label = textwrap.shorten(label, width=20, placeholder="...")
            ax.axvline(x, color="gray", linestyle=":")
            if alignment == 'top':
                y = ymin+0.98*(ymax-ymin)
            elif alignment == 'bottom':
                y = ymin+0.02*(ymax-ymin)
            else:
                raise ValueError(f"Unsupported alignment: '{alignment}'")
            ax.text(
                x, y,
                s=f'{label}\n',
                color="gray",
                rotation=90,
                horizontalalignment="center",
                verticalalignment=alignment,                
            )
    return None


def plot_testcount_forecast(
    result: pandas.Series,
    m: preprocessing.fbprophet.Prophet,
    forecast: pandas.DataFrame,
    considered_holidays: preprocessing.NamedDates, *,
    ax: matplotlib.axes.Axes=None
) -> matplotlib.axes.Axes:
    """ Helper function for plotting the detailed testcount forecasting result.

    Parameters
    ----------
    result : pandas.Series
        the date-indexed series of smoothed/predicted testcounts
    m : fbprophet.Prophet
        the prophet model
    forecast : pandas.DataFrame
        contains the prophet model prediction
    holidays : dict of { datetime : str }
        dictionary of the holidays that were used in the model
    ax : optional, matplotlib.axes.Axes
        an existing subplot to use

    Returns
    -------
    ax : matplotlib.axes.Axes
        the (created) subplot that was plotted into
    """
    if not ax:
        _, ax = pyplot.subplots(figsize=(13.4, 6))
    m.plot(forecast[forecast.ds >= m.history.set_index('ds').index[0]], ax=ax)
    ax.set_ylim(bottom=0)
    ax.set_xlim(pandas.to_datetime('2020-03-01'))
    plot_vlines(ax, considered_holidays, alignment='bottom')
    ax.legend(frameon=False, loc='upper left', handles=[
        ax.scatter([], [], color='black', label='training data'),
        ax.plot([], [], color='blue', label='prediction')[0],
        ax.plot(result.index, result.values, color='orange', label='result')[0],
    ])
    ax.set_ylabel('total tests')
    ax.set_xlabel('')
    return ax


def plot_testcount_components(
    m: preprocessing.fbprophet.Prophet,
    forecast: pandas.DataFrame,
    considered_holidays: preprocessing.NamedDates
) -> typing.Tuple[matplotlib.figure.Figure, typing.Sequence[matplotlib.axes.Axes]]:
    """ Helper function to plot components of the Prophet forecast.

    Parameters
    ----------
    m : fbprophet.Prophet
        the prophet model
    forecast : pandas.DataFrame
        contains the prophet model prediction
    considered_holidays : preprocesssing.NamedDates
        the dictionary of named dates that were considered by the prophet model

    Returns
    -------
    figure : matplotlib.figure.Figure
        the created figure object
    axs : array of matplotlib Axes
        the subplots within the figure
    """
    fig = m.plot_components(
        forecast[forecast.ds >= m.history.set_index('ds').index[0]],
        figsize=(13.4, 8),
        weekly_start=1,
    )
    axs = fig.axes
    for ax in axs:
        ax.set_xlabel('')
    axs[0].set_ylim(0)
    axs[1].set_ylim(-1)
    plot_vlines(axs[0], considered_holidays, alignment='bottom')
    plot_vlines(axs[1], {k:'' for k in considered_holidays.keys()}, alignment='bottom')
    axs[0].set_xlim(pandas.to_datetime('2020-03-01'))
    axs[1].set_xlim(pandas.to_datetime('2020-03-01'))
    return fig, axs


def plot_details(
    idata: arviz.InferenceData,
    *,
    fig=None,
    axs: numpy.ndarray=None,
    vlines: typing.Optional[preprocessing.NamedDates] = None,
    actual_tests: typing.Optional[pandas.Series] = None,
    plot_positive: bool=False,
    rt_comparisons: typing.Dict[
        str,
        typing.Tuple[pandas.Series, typing.Optional[pandas.Series], typing.Optional[pandas.Series], str]
    ]=None,
    locale_key: str=None,
    label_translations: typing.Dict[str, str]=None,
    license: str=None,
):
    """ Creates a figure that shows the most important results of the model for a particular region.

    Parameters
    ----------
    idata : arviz.InferenceData
        contains the MCMC trace and observed data
    fig : optional, Figure
        a figure to use (in combination with [axs] argument)
    axs : optional, array of axes
        four subplot axes to plot into (curves, testcounts, probability, r_t)
    vlines : preprocessing.NamedDates
        dictionary of { datetime.datetime : str } for drawing vertical lines
    actual_tests : optional, pandas.Series
        date-indexed series of daily confirmed cases
    plot_positive : optional, bool
        setting to include the prediction of confirmed cases that is directly comparable with the observations
    rt_comparisons : optional, dict of tuples
        can be used to include additional r_t value predictions
        the keys become labels for the legend
        the values are
            a date-indexed pandas series of r_t values
            (optional) a date-indexed pandas series of the lower bound
            (optional) a date-indexed pandas series of the upper bound
            the color for the line/interval
    locale_key : str
        allows to set the local via local.setlocale(locale.LC_TIME, locale_key)
        for example "de_DE.UTF-8"
    label_translations : dict
        can be used to override labels in the plot (see code for the defaults)
    license : optional, str
        a license text to be included in the plot

    Returns
    -------
    fig : matplotlib.Figure
        the figure
    (top, center, bottom) : tuple
        the subplots
    """
    if locale_key:
        locale.setlocale(locale.LC_TIME, locale_key)
    if label_translations is None:
        label_translations = {}
    label_translations = {
        "curves_ylabel": "per day",
        "testcounts_ylabel": "daily\ntests",
        "probability_ylabel": "probability\nof $R_t$>1",
        "rt_ylabel": "$R_t$",
        "curve_infections": "infections",
        "curve_adjusted": "testing delay adjusted",
        "bar_positive": "positive tests",
        "bar_actual_tests": "actual tests",
        "curve_predicted_tests": "predicted tests",
        **label_translations
    }

    # plot symptom onsets and R_t posteriors
    if not (fig != None and axs is not None):
        fig, axs = pyplot.subplots(
            nrows=4,
            gridspec_kw={"height_ratios": [3, 1, 1, 2]},
            dpi=140,
            figsize=(10, 8),
            sharex="col",
        )
    ax_curves, ax_testcounts, ax_probability, ax_rt = axs
    handles = []

    scale_factor = model.get_scale_factor(idata)

    # ============================================ curves
    # top subplot: counts
    # "infections" and "test_adjusted_positive" are modeled relative.
    var_label_colors= [
        ('infections', label_translations["curve_infections"], cm.Reds),
        ('test_adjusted_positive', label_translations["curve_adjusted"], cm.Greens)
    ]
    for var, label, cmap in var_label_colors:
        pymc3.gp.util.plot_gp_dist(
            ax_curves,
            x=idata.posterior[var].date.values[3:],
            samples=((idata.posterior[var].stack(sample=('chain', 'draw')) * scale_factor).values.T)[:, 3:],
            samples_alpha=0,
            palette=cmap,
            fill_alpha=.15,
        )
        handles.append(ax_curves.fill_between([], [], color=cmap(100), label=label))
    if plot_positive:
        # include the prediction of confirmed cases that is directly comparable with the observations
        pymc3.gp.util.plot_gp_dist(
            ax_curves,
            x=idata.posterior["positive"].date.values[3:],
            samples=(idata.posterior["positive"].stack(sample=('chain', 'draw')).values.T)[:, 3:],
            samples_alpha=0,
            palette="Blues",
            fill_alpha=.15,
        )
    ax_curves.set_ylabel(label_translations["curves_ylabel"], fontsize=12)

    handles.append(
        ax_curves.bar(
            idata.constant_data.observed_positive.date.values,
            idata.constant_data.observed_positive,
            label=label_translations["bar_positive"],
            alpha=0.5,
        )
    )
    ax_curves.legend(
        handles=[
            *handles,
        ],
        loc="upper left",
        frameon=False,
    )

    # ============================================ testcounts
    ax_testcounts.plot(
        idata.constant_data.tests.date.values,
        idata.constant_data.tests.values,
        color="orange",
        label=label_translations["curve_predicted_tests"],
    )
    if actual_tests is not None:
        ax_testcounts.bar(
            actual_tests.index,
            actual_tests.values,
            label=label_translations["bar_actual_tests"],
        )
    ax_testcounts.legend(frameon=False, loc="upper left")
    ax_testcounts.set_ylabel(label_translations["testcounts_ylabel"], fontsize=12)

    # ============================================ probabilities
    ax_probability.plot(
        idata.posterior.date, (idata.posterior.r_t > 1).mean(dim=("chain", "draw"))
    )
    ax_probability.set_ylim(0, 1)
    ax_probability.set_ylabel(label_translations["probability_ylabel"], fontsize=12)

    # ============================================ R_t
    pymc3.gp.util.plot_gp_dist(
        ax=ax_rt,
        x=idata.posterior.date.values,
        samples=idata.posterior.r_t.stack(sample=("chain", "draw")).T.values,
        samples_alpha=0,
    )
    ax_rt.axhline(1, linestyle=":")
    ax_rt.set_ylabel(label_translations["rt_ylabel"], fontsize=12)
    ax_rt.xaxis.set_major_locator(
        matplotlib.dates.WeekdayLocator(interval=1, byweekday=matplotlib.dates.MO)
    )
    ax_rt.xaxis.set_minor_locator(matplotlib.dates.DayLocator())
    ax_rt.xaxis.set_tick_params(rotation=90)
    ax_rt.set_ylim(0, 2.5)
    ax_rt.set_xlim(right=datetime.datetime.utcnow() + datetime.timedelta(hours=12))

    # additional R_t entries
    if rt_comparisons:
        for label, (comp_rt, lower, upper, color) in rt_comparisons.items():
            ax_rt.plot(
                comp_rt.index, 
                comp_rt.values, 
                color=color,
                label=label
            )
            if lower is not None and upper is not None:
                ax_rt.fill_between(
                    lower.index,
                    lower.values, upper.values,
                    alpha=.15, color=color,
                )
        ax_rt.legend(frameon=False)

    # ============================================ figure elements
    if license:
        # embed license notice directly in the plot
        axs[0].text(
            1.0, 1.01,
            license,
            transform=axs[0].transAxes,
            color='#AAAAAA',
            horizontalalignment='right',
            verticalalignment='bottom',
            fontsize=8,
        )
    if vlines:
        plot_vlines(ax_testcounts, {k:'' for k in vlines.keys()}, alignment='top')
        plot_vlines(ax_probability, {k:'' for k in vlines.keys()}, alignment='top')
        plot_vlines(ax_rt, vlines, alignment='bottom')

    fig.align_ylabels(axs)
    fig.tight_layout()
    return fig, axs


def plot_thumbnails(idata, *, locale_key=None, license=True):
    if locale_key:
        locale.setlocale(locale.LC_TIME, locale_key)
    fig, ax = pyplot.subplots(dpi=120, figsize=(6, 4))

    pymc3.gp.util.plot_gp_dist(
        ax=ax,
        x=idata.posterior.date.values,
        samples=idata.posterior.r_t.stack(sample=("chain", "draw")).T.values,
        samples_alpha=0,
    )
    ax.axhline(1, linestyle=":")
    ax.set_ylabel("$R_t$", fontsize=20)
    ax.xaxis.set_major_locator(
        matplotlib.dates.MonthLocator(interval=1),
    )
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter('%b'))
    ax.xaxis.set_minor_locator(matplotlib.dates.WeekdayLocator(interval=1, byweekday=matplotlib.dates.MO))
    ax.xaxis.set_tick_params(rotation=0, labelsize=16)
    ax.yaxis.set_tick_params(labelsize=16)
    ax.set_ylim(0, 2.5)
    ax.set_xlim(idata.posterior.date[0], datetime.datetime.today())

    # embed license notice directly in the plot
    if license:
        ax.text(
            0.03, 0.03,
            license,
            transform=ax.transAxes,
            color='#AAAAAA',
            horizontalalignment='left',
            fontsize=6,
        )

    fig.tight_layout()
    return fig, ax
