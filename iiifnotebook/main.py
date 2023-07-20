"""
In this implementation the ax is considered the canvas. We use imshow extents
properties to plot the images in part of the canvases
"""
from logging import warning
from IPython.display import display
import ipywidgets as widgets

from skimage import io

from matplotlib.widgets import RectangleSelector
import matplotlib.patches as patches
import matplotlib.pyplot as plt

import numpy as np
import requests
from io import StringIO
from html.parser import HTMLParser
import psutil

from collections import defaultdict

global RUNNING_IN_JUPYTER
RUNNING_IN_JUPYTER = any(
    [i.endswith("bin/jupyter-notebook") for i in psutil.Process().parent().cmdline()]
)


class IIIFviewer:
    def __init__(self, url, preferred_language="en"):
        """An embedded image viewer can read IIIF manifest compliant with
        presentation API v.3.

        Args:
            url (str): The url of the manifest
            preferred_language (str, optional): The preferred language of the
            manifest if available. Defaults to 'en'.
        """
        self.url = url
        self.preferred_language = preferred_language
        self.manifest = None
        self.service_url = None
        self._canvas_info_items = []
        self._canvas_info_labels = []
        self.canvas_info = widgets.Accordion()
        self._cavnas_info_html = widgets.HTML("None")
        self._canvasMetadataTable = widgets.HTML("None")
        self._annotations_html = widgets.HTML("None")
        self.contentresource_info = widgets.Accordion()
        self._ccontentresource_info_html = widgets.HTML("None")
        self._contentresource_annotations_html = widgets.HTML("")
        self._lcnv_width = None
        self._lcnv_height = None
        self._limgwidth = None
        self._limgheight = None
        self._lannotations_count = 0
        self._tab_nest = None
        self.lastRoI = None
        self.lastRoIURL = None
        self.RoIs = defaultdict(list)
        self.ROIsURLs = defaultdict(list)
        self.region_x = None
        self.region_y = None
        self.region_width = None
        self.region_height = None
        self.image = None
        self._imagePlotted = False
        # Must be the last
        self.openData()

    def get_currentImageURL(self, region=None, preview=False):
        """Return the URL of the image shown on the visualizer.

        Args:
            region (str, optional): An optional region can be provided otherwise
            will be use the region written on the control widget. Defaults to None.
            preview (bool, optional): If True the image return will have the size
            specified on the preview widget of the controls panel. Defaults to False.

        Raises:
            ValueError: _description_

        Returns:
            str: A string containing the url for the image.
        """
        if self.service_url is None:
            # raise ValueError("Image does not have service")
            return None
        if region is None:
            region = self.W_region.value
        if preview:
            size = self.W_preview_size.value
        else:
            size = self.W_final_size.value

        # TODO: save region parameters
        if region.startswith("pct:"):
            print("Not implemented")
            region = region.strip("pct:")
            xi, yi, wi, hi = map(float, region.split(","))
            self.region_x = xi / 100 * self._lcnv_width
            self.region_y = yi / 100 * self._lcnv_height
            self.region_width = wi / 100 * self._lcnv_width
            self.region_height = hi / 100 * self._lcnv_height
        elif "," in region:
            xi, yi, wi, hi = map(float, region.split(","))
            self.region_x = xi
            self.region_y = yi
            self.region_width = wi
            self.region_height = hi
        else:
            self.region_x = None
            self.region_y = None
            self.region_width = None
            self.region_height = None
        return "/".join(
            [
                self.service_url,
                region,
                size,
                str(self.W_rot_fld.value),
                ".".join([self.W_quality.value, self.W_img_format.value]),
            ]
        )

    def get_RoIURL(self, canvasIndex=None, ROIindex=0):
        """_summary_

        Args:
            region (_type_, optional): _description_. Defaults to None.
            canvasIndex (_type_, optional): _description_. Defaults to None.

        Returns:
            _type_: _description_
        """
        if canvasIndex is None:
            canvasIndex = self.W_canvasID.value
        if canvasIndex in self.RoIs:
            RoI = self.RoIs[canvasIndex]
            region = ",".join(map(str, self.RoIs[canvasIndex][ROIindex][0]))
        return self.get_currentImageURL(region=f"pct:{region}")

    def get_datafromURLs(self, urls):
        if isinstance(urls, list):
            data = np.dstack([io.imread(url) for url in urls])
        else:
            data = io.imread(urls)
        return data

    def get_stackfromChoices(self, canvasIndex=None, preview=False):
        # TODO: make it work for the newer version
        if canvasIndex is None:
            canvasIndex = self.W_canvasID.value
        canvas = self.manifest["items"][canvasIndex]
        urls = []
        for cnvitm in canvas["items"]:
            if cnvitm["type"] == "AnnotationPage":
                for ann in cnvitm["items"]:
                    if ann["motivation"] == "painting":
                        body = ann["body"]
                        if body["type"] == "Choice":
                            for choice in body["items"]:
                                if "service" in choice:
                                    # TODO: iterate
                                    baseurl = choice["service"][0]["id"]
                                    if preview:
                                        size = self.W_preview_size.value
                                    else:
                                        size = self.W_final_size.value
                                    if canvasIndex in self.RoIs:
                                        RoI = self.RoIs[canvasIndex]
                                        region = ",".join(
                                            map(str, self.RoIs[canvasIndex])
                                        )
                                        region = f"pct:{region}"
                                        url = "/".join(
                                            [
                                                baseurl,
                                                region,
                                                size,
                                                str(self.W_rot_fld.value),
                                                ".".join(
                                                    [
                                                        self.W_quality.value,
                                                        self.W_img_format.value,
                                                    ]
                                                ),
                                            ]
                                        )
                                        urls.append(url)
                                else:
                                    url = choice["id"]
                                    urls.append(url)
        print(urls)
        return self.get_datafromURLs(urls)

    def openData(self, forceReload=False):
        if not RUNNING_IN_JUPYTER:
            warning("The visualizer is designed to work with Jupyter notebook.")
        firstopening = True

        def tryLanguage(iiifobject):
            if self.preferred_language in iiifobject:
                values = iiifobject[self.preferred_language]
            elif "none" in iiifobject:
                values = iiifobject["none"]
            else:
                values = list(iiifobject.values())[0]
                print(f"language {self.preferred_language} not available.")
            return " ".join(values)

        def saveROIbutton(arg):
            self.RoIs[self.W_canvasID.value].append(
                (self.lastRoI, self.W_RoI_comment.value)
            )
            self.ROIsURLs[self.W_canvasID.value].append(self.lastRoIURL)

        def requestResource(url):
            response = requests.get(url)
            if response.ok:
                self.manifest = response.json()
                # TODO: why I can't read the self.manifest
                mnf = response.json()
                if mnf["type"] == "Collection":
                    print(f"Select a Manifest:")
                    for ind, item in enumerate(mnf["items"]):
                        label = tryLanguage(item["label"])
                        print(f"{ind+1} - {item['type']}: {label} {item['id']} ")
                    manifestIndex = int(input("Select manifest index: ")) - 1
                    return requestResource(mnf["items"][manifestIndex]["id"])
                return mnf
            else:
                raise ValueError("Could not get the Manifest.")

        if self.manifest is None or forceReload:
            mnf = requestResource(self.url)
            # {region}/{size}/{rotation}/{quality}.{format}
            self.W_canvasID = widgets.BoundedIntText(
                description="Canvas:", min=0, max=len(mnf["items"]) - 1
            )
            # language = widgets.Text(
            #    value=self.preferred_language,
            #    placeholder=self.preferred_language,
            #    description='Language:',
            #    disabled=False
            # )
            self.W_annotations = widgets.Checkbox(
                value=True, description="Show annotations", disabled=False
            )
            self.W_quality = widgets.Text(
                value="default",
                placeholder="default",
                description="Quality:",
                disabled=False,
            )
            self.W_region = widgets.Text(
                value="full", placeholder="full", description="Region:", disabled=False
            )
            self.W_img_format = widgets.Text(
                value="jpg", placeholder="jpg", description="Format:", disabled=False
            )
            self.W_rot_fld = widgets.IntText(description="Rotation:", value=0)
            self.W_preview_size = widgets.Text(
                value="400,", placeholder="400,", description="Preview:", disabled=False
            )
            self.W_final_size = widgets.Text(
                value="max",
                placeholder="max",
                description="Final Size:",
                disabled=False,
            )
            self.W_choiceelem = widgets.Dropdown(
                options=["none"],
                value="none",
                description="Choices:",
                disabled=False,
            )

            self.W_RoI_comment = widgets.Textarea(
                description="Comment:", disabled=False
            )
            self.W_saveROIbtn = widgets.Button(description="Save ROI")
            self.W_saveROIbtn.on_click(saveROIbutton)
            self.W_refreshbtn = widgets.Button(description="Refresh")
            self.W_loadZoombtn = widgets.Button(description="Load Zoom")

        else:
            mnf = self.manifest
            firstopening = False

        def select_callback(eclick, erelease):
            """
            Callback for line selection.

            *eclick* and *erelease* are the press and release events.
            """
            x1, y1 = eclick.xdata, eclick.ydata
            x2, y2 = erelease.xdata, erelease.ydata

            width = x2 - x1
            height = y2 - y1
            self.lastRoIabsolute = [x1,y1,width,height]
            self.lastRoI = [
                round(x1 / self._lcnv_width * 100, 2),
                round(y1 / self._lcnv_height * 100, 2),
                round(width / self._lcnv_width * 100, 2),
                round(height / self._lcnv_height * 100, 2),
            ]
            region = ",".join(map(str, self.lastRoI))
            self.lastRoIURL = self.get_currentImageURL(region=f"pct:{region}")

        def toggle_selector(event):
            print("Key pressed.")
            if event.key == "t":
                for selector in selectors:
                    name = type(selector).__name__
                    if selector.active:
                        print(f"{name} deactivated.")
                        selector.set_active(False)
                    else:
                        print(f"{name} activated.")
                        selector.set_active(True)

        def getTarget(iiifObjectWithTarget):
            target = iiifObjectWithTarget["target"]
            if isinstance(target, str):
                return ("region", target.split("#xywh="))
            elif isinstance(target, dict):
                if "source" in target and "selector" not in target:
                    return ("region", target["source"].split("#xywh="))
                if "source" in target and "selector" in target:
                    if target["selector"]["type"] == "PointSelector":
                        x = target["selector"].get("x")
                        y = target["selector"].get("y")
                        t = target["selector"].get("t")
                        return ("PointSelector", (x, y, t))
                    if target["selector"]["type"] == "ImageApiSelector":
                        if "region" in target["selector"]:
                            return ("region", target["selector"]["region"])
                    else:
                        raise ValueError(f"{target['selector']['type']} not supported")

        def createHTMLtable(keyValueObj):
            """
            Create an HTML table from a key value dict.
            """
            table = ["<table>"]
            for row in keyValueObj:
                label = tryLanguage(row["label"])
                value = tryLanguage(row["value"])
                trow = f"<tr><td>{label}: </td><td>{value}</td></tr>"
                table.append(trow)
            table.append("</table>")
            value = "".join(table)
            return value

        def createTable(keyValueObj):
            """
            Create an HTML table widget from a key value dict.
            """
            createHTMLtable
            htmlTable = widgets.HTML(
                value=createHTMLtable(keyValueObj),
            )
            return htmlTable

        ## Utility for stripping HTML
        ## Credits: https://stackoverflow.com/a/925630/2132157
        class MLStripper(HTMLParser):
            def __init__(self):
                super().__init__()
                self.reset()
                self.strict = False
                self.convert_charrefs = True
                self.text = StringIO()

            def handle_data(self, d):
                self.text.write(d)

            def get_data(self):
                return self.text.getvalue()

        def strip_tags(html):
            s = MLStripper()
            s.feed(html)
            return s.get_data()

        manifestLabel = tryLanguage(mnf["label"])
        # Matplotlib interface
        self.fig = plt.figure(manifestLabel)
        self.ax = self.fig.subplots(1)
        ## Rectangle selecotors
        selectors = []
        selectors.append(
            RectangleSelector(
                self.ax,
                select_callback,
                useblit=True,
                button=[1, 3],  # disable middle button
                minspanx=5,
                minspany=5,
                spancoords="pixels",
                interactive=True,
            )
        )
        self.fig.canvas.mpl_connect("key_press_event", toggle_selector)

        def on_xlims_change(event_ax):
            print("updated xlims: ", event_ax.get_xlim())

        def on_ylims_change(event_ax):
            print("updated ylims: ", event_ax.get_ylim())
            if self._imagePlotted:
                x1,x2 = event_ax.get_xlim()
                y1,y2 = event_ax.get_ylim()
                x = int(x1 + 0.5)
                y = int(y2 + 0.5)
                self.log2 = [x1,x2,y1,y2]
                width = int(x2 - x1)
                height = int(y1 - y2)
                region = list(map(str,[x,y,width,height]))
                if width != self._lcnv_width and height != self._lcnv_height:
                    url = self.get_currentImageURL(region=",".join(region))
                    self.zoomregion = url
                    self.zoomextent = (x1, x2, y1, y2)
                    #img = io.imread(url)
                    #self.log = url
                    #extent = (x1, x2, y1, y2)
                    #self.ax.imshow(img, extent=extent)


        self.ax.callbacks.connect('xlim_changed',on_xlims_change)
        self.ax.callbacks.connect('ylim_changed',on_ylims_change)
        plt.show()

        ## Attribution
        requiredStatementTable = None
        if "requiredStatement" in mnf:
            # watermark on the image
            label = strip_tags(tryLanguage(mnf["requiredStatement"]["label"]))
            value = strip_tags(tryLanguage(mnf["requiredStatement"]["value"]))
            textstr = f"{label}:{value}"
            self.ax.set_ylabel(textstr, fontsize=6)

        def get_annotations(annopage_item):
            # we check that we want to display the annotations
            if self.W_annotations.value:
                selectortype, fragments = getTarget(annopage_item)
                if selectortype == "region":
                    if len(fragments) > 1:
                        fragment = fragments[-1]
                        if fragment.startswith("pct:"):
                            print("Not implemented")
                            fragment = fragment.strip("pct:")
                            xi, yi, wi, hi = map(float, fragment.split(","))
                            x = xi / 100 * self._lcnv_width
                            y = yi / 100 * self._lcnv_height
                            width = wi / 100 * self._lcnv_width
                            height = hi / 100 * self._lcnv_height
                        else:
                            x, y, width, height = map(float, fragment.split(","))

                    else:
                        # whole canvas case
                        x = 0
                        y = 0
                        width = self._lcnv_width
                        height = self._lcnv_height
                    rect = patches.Rectangle(
                        (x, y),
                        width,
                        height,
                        linewidth=4,
                        edgecolor="r",
                        facecolor="none",
                    )
                    # Add the patch to the Axes
                    self.ax.add_patch(rect)
                if selectortype == "PointSelector":
                    x, y, _ = fragments
                    self.ax.scatter(x, y)
                    #self.ax.set_xlim(0,self._limgwidth)
                    #self.ax.set_ylim(0,self._limgheight)
            # if we don't want to display them we romove any
            else:
                for p in reversed(self.ax.patches):p.remove()

        def check_body(body):
            if body["type"] == "SpecificResource":
                return (
                    f"<a href={body['source']} target=_blank>{body['source']} </a> <br>"
                )
            if body["type"] == "TextualBody":
                return body["value"] + "<br>"

        def get_annobodies(annoitem):
            if isinstance(annoitem["body"], list):
                annostr = ""
                for body in annoitem["body"]:
                    annostr += check_body(body)
            else:
                annostr = f"{self._lannotations_count} - {check_body(annoitem['body'])} - {getTarget(annoitem)} <br>"
            return annostr

        def update_image(canvasindex):
            # I can't self.ax.cla() here because will stop the ROI selctor.
            # for i in self.ax.images: i.remove()
            for p in reversed(self.ax.patches):p.remove()
            #for l in self.ax.lines
            for c in self.ax.collections: c.remove()
            canvas = mnf["items"][canvasindex]
            self._lcnv_width = int(canvas["width"])
            self._lcnv_height = int(canvas["height"])
            self.service_url = None
            for cnvitm in canvas["items"]:
                if cnvitm["type"] == "AnnotationPage":
                    for ann in cnvitm["items"]:
                        if ann["motivation"] == "painting":
                            body = ann["body"]
                            if body["type"] == "Choice":
                                if self.W_choiceelem.value == "none":
                                    ic = body["items"]
                                    opts = [
                                        (tryLanguage(j["label"]), i)
                                        for i, j in enumerate(ic)
                                    ]
                                    self.W_choiceelem.options = opts
                                    contentresource = body["items"][0]
                                else:
                                    contentresource = body["items"][
                                        self.W_choiceelem.value
                                    ]

                            if body["type"] == "Image":
                                contentresource = body
                                self.W_choiceelem.disabled = True

                            if body["type"] == "SpecificResource":
                                contentresource = body["source"]

                            if "service" in contentresource:
                                for service in contentresource["service"]:

                                    if service["type"].startswith("ImageService"):
                                        region = None
                                        self.service_url = service["id"]
                                        if "selector" in body:
                                            if body["selector"]["type"] in [
                                                "iiif:ImageApiSelector",
                                                "ImageApiSelector",
                                            ]:
                                                region = body["selector"]["region"]

                                        imageurl = self.get_currentImageURL(
                                            preview=True, region=region
                                        )
                                        if "annotations" in service:
                                            annostr = ""
                                            for annopage in service["annotations"]:
                                                for item in annopage["items"]:
                                                    self._lannotations_count += 1
                                                    annostr += get_annobodies(
                                                        annoitem=item
                                                    )
                                                    get_annotations(item)
                                            self._contentresource_annotations_html.value += (
                                                annostr
                                            )
                            else:
                                imageurl = contentresource["id"]
                                self.W_final_size.disabled = True
                                self.W_preview_size.disabled = True
                                self.W_rot_fld.disabled = True
                                self.W_quality.disabled = True
                                self.W_region.disabled = True
                                self.W_img_format.disabled = True

                            ## Read the image
                            self.img = io.imread(imageurl)
                            # used by the selector
                            self._limgwidth = self.img.shape[1]
                            self._limgheight = self.img.shape[0]
                            if "annotations" in contentresource:
                                annostr = ""
                                for annopage in contentresource["annotations"]:
                                    for item in annopage["items"]:
                                        annostr += get_annobodies(annoitem=item)
                                        get_annotations(item)
                                self._contentresource_annotations_html.value += annostr

                            generalinfo = "<br>".join(
                                [
                                    f"{i}: {contentresource[i]}"
                                    for i in contentresource
                                    if isinstance(contentresource[i], (str, float, int))
                                ]
                            )
                            self._ccontentresource_info_html.value = generalinfo

            cmap = None
            if len(self.img.shape) < 3:
                cmap = "gray"
            if self.image is None:
                extent = (-0.5, self._lcnv_width-0.5, self._lcnv_height-0.5, -0.5)
                self.image = self.ax.imshow(self.img, cmap=cmap,extent=extent)
            #self.ax.set_aspect('equal', adjustable='box')
            else:
                self.image.set_data(self.img)
            self._imagePlotted = True
            #self.fig.canvas.draw()
            if "label" in canvas:
                title = tryLanguage(canvas["label"])
                self.ax.set_title(title)

            ## Canvas INFOS
            ## width and height
            # bdy = canvas['body']
            generalinfo = "<br>".join(
                [
                    f"{i}: {canvas[i]}"
                    for i in canvas
                    if isinstance(canvas[i], (str, float, int))
                ]
            )
            self._cavnas_info_html.value = generalinfo
            if "metadata" in canvas:
                self._canvasMetadataTable.value = createHTMLtable(canvas["metadata"])

            ### Annotations
            if "annotations" in canvas:
                annostr = ""
                for annopage in canvas["annotations"]:
                    for item in annopage["items"]:
                        self._lannotations_count += 1
                        annostr += get_annobodies(annoitem=item)
                        get_annotations(item)
                self._annotations_html.value = annostr

            if self._lannotations_count > 0:
                self.W_annotations.disabled = False
            else:
                self.W_annotations.disabled = True
            # Sow image
            plt.show()

        def view_image(change):
            # using self.ax.cla() we will remove also the connector
            i = self.W_canvasID.value
            if i < len(mnf["items"]):
                update_image(i)
            else:
                print("Canvas number exceeds the number of Canvas")

        def load_zoom(change):
            img = io.imread(self.zoomregion)
            self.ax.imshow(img,extent=self.zoomextent)
            self.fig.canvas.draw()

        def getseeAlso(obj):
            seeAlsohtml = ""
            for seeAlso in obj["seeAlso"]:
                label = tryLanguage(seeAlso["label"])
                url = seeAlso["id"]
                seeAlsohtml += f"<a href={url} target=_blank>{label} </a>"
                if "type" in seeAlso:
                    seeAlsohtml += f"{seeAlso['type']} "
                if "format" in seeAlso:
                    seeAlsohtml += f"{seeAlso['format']}"
                if "profile" in seeAlso:
                    seeAlsohtml += f" Profile: <a href={seeAlso['profile']} target=_blank>{seeAlso['profile']} </a>"
                seeAlsohtml += "<br>"
            return seeAlsohtml

        self.W_annotations.observe(view_image, names="value")
        self.W_choiceelem.observe(view_image, names="value")
        self.W_canvasID.observe(view_image, names="value")
        accordionitems = []
        accordionlabels = []
        if "summary" in mnf:
            summary = widgets.HTML(tryLanguage(mnf["summary"]))
            accordionitems.append(summary)
            accordionlabels.append("Summary")
        if "metadata" in mnf:
            metadatatable = createTable(mnf["metadata"])
            accordionitems.append(metadatatable)
            accordionlabels.append("Metadata")
        if "requiredStatement" in mnf:
            requiredStatementTable = createTable([mnf["requiredStatement"]])
            accordionitems.append(requiredStatementTable)
            accordionlabels.append("Required statement")
        if "provider" in mnf:
            providers = mnf["provider"]
            htmlprovider = "<ul>"
            for provider in providers:
                htmlprovider = "<li>"
                if "logo" in provider:
                    logos = provider["logo"]
                    for logo in logos:
                        urllogo = logo["id"]
                        htmlprovider += f"<img src={urllogo} width=200px>"
                htmlprovider += provider["id"]
                if "homepage" in provider:
                    for homepage in provider["homepage"]:
                        homepageid = homepage["id"]
                        homepagelabel = tryLanguage(homepage["label"])
                        htmlprovider += (
                            f"- <a href={homepageid} target=_blank>{homepagelabel} </a>"
                        )
                htmlprovider += "<br>"
                if "seeAlso" in provider:
                    htmlprovider += getseeAlso(provider)
                htmlprovider += "</li>"
            htmlprovider += "</ul>"
            provider = widgets.HTML(
                value=htmlprovider,
            )
            accordionitems.append(provider)
            accordionlabels.append("Providers")

        if "rights" in mnf:
            rights = widgets.HTML(value=f"<a href={mnf['rights']}>{mnf['rights']}</a>")
            accordionitems.append(rights)
            accordionlabels.append("Rights")
        if "navDate" in mnf:
            navDate = widgets.HTML(value=mnf["navDate"])
            accordionitems.append(navDate)
            accordionlabels.append("navDate")
        if "rendering" in mnf:
            renderinghtml = ""
            for render in mnf["rendering"]:
                label = tryLanguage(render["label"])
                url = render["id"]
                renderinghtml += f"<a href={url} target=_blank>{label} </a><br>"
            rendering = widgets.HTML(
                value=renderinghtml,
            )
            accordionitems.append(rendering)
            accordionlabels.append("Rendering")

        if "seeAlso" in mnf:
            seeAlsohtml = getseeAlso(mnf)
            seeAlsoWidget = widgets.HTML(
                value=seeAlsohtml,
            )
            accordionitems.append(seeAlsoWidget)
            accordionlabels.append("seeAlso")
        ## LAYOUT TABS AND ACCORDIONS
        if firstopening:
            self.W_refreshbtn.on_click(view_image)
            self.W_loadZoombtn.on_click(load_zoom)
            self._tab_nest = widgets.Tab()
            # accordion = widgets.Accordion(children=[widgets.IntSlider(), widgets.Text()], titles=('Slider', 'Text'))
            self._tab_nest.set_title(0, "Controls")
            self._tab_nest.set_title(1, "Manifest infos")
            self._tab_nest.set_title(2, "Canvas infos")
            self._tab_nest.set_title(3, "Contentresource infos")
            # Accordion manifest items
            manifest_info = widgets.Accordion(children=accordionitems)
            for ind, albl in enumerate(accordionlabels):
                manifest_info.set_title(ind, albl)
            # Accordion canvas info
            self.canvas_info = widgets.Accordion(
                children=[
                    self._cavnas_info_html,
                    self._annotations_html,
                    self._canvasMetadataTable,
                ]
            )
            self.canvas_info.set_title(0, "General infos")
            self.canvas_info.set_title(1, "Annotations")
            self.canvas_info.set_title(2, "Metadata")
            HBOX = widgets.HBox(
                [self.W_canvasID, self.W_choiceelem, self.W_annotations]
            )
            HBOX2 = widgets.HBox(
                [self.W_region, self.W_preview_size, self.W_final_size]
            )
            HBOX3 = widgets.HBox([self.W_rot_fld, self.W_quality, self.W_img_format])
            HBOX4 = widgets.HBox(
                [self.W_RoI_comment, self.W_saveROIbtn, self.W_refreshbtn, self.W_loadZoombtn]
            )
            contentresource = widgets.Accordion(
                children=[
                    self._ccontentresource_info_html,
                    self._contentresource_annotations_html,
                ]
            )
            contentresource.set_title(0, "General infos")
            contentresource.set_title(1, "Annotations")

            Cntr_layout = widgets.VBox([HBOX, HBOX2, HBOX4])
            # HBOX = widgets.GridBox([self.W_canvasID,rot_fld,preview_size,final_size,valid], layout=widgets.Layout(grid_template_columns="repeat(3, 200px)"))
            self._tab_nest.children = [
                Cntr_layout,
                manifest_info,
                self.canvas_info,
                contentresource,
            ]
            display(self._tab_nest)
        update_image(0)
        return self._tab_nest
